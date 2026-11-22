from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .models import EDLDocument, OutputSettings


class FFmpegError(RuntimeError):
    pass


class FFmpegEngine:
    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def probe(self, path: Path) -> dict[str, Any]:
        result = subprocess.run(
            [
                self.ffprobe_bin,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    @staticmethod
    def has_audio(probe: dict[str, Any]) -> bool:
        return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))

    def _run(self, command: list[str]) -> None:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout)[-5000:]
            raise FFmpegError(f"FFmpeg command failed ({result.returncode}): {detail}")

    @staticmethod
    def _video_filter(output: OutputSettings) -> str:
        return (
            f"scale={output.width}:{output.height}:force_original_aspect_ratio=increase,"
            f"crop={output.width}:{output.height},fps={output.fps},setsar=1"
        )

    def prepare_base(
        self,
        source: Path,
        destination: Path,
        output: OutputSettings,
        edl_path: Path | None = None,
        crf: int = 18,
        preset: str = "medium",
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not source.is_file():
            raise FileNotFoundError(f"Source video not found: {source}")
        source_probe = self.probe(source)
        if not any(s.get("codec_type") == "video" for s in source_probe.get("streams", [])):
            raise ValueError(f"Source contains no video stream: {source}")
        if edl_path:
            self._render_edl(source, destination, output, edl_path, source_probe, crf, preset)
        else:
            self._normalize(source, destination, output, source_probe, crf, preset)
        return destination

    def _normalize(
        self,
        source: Path,
        destination: Path,
        output: OutputSettings,
        source_probe: dict[str, Any],
        crf: int,
        preset: str,
    ) -> None:
        command = [
            self.ffmpeg_bin, "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", self._video_filter(output),
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
        ]
        if self.has_audio(source_probe):
            command += ["-c:a", "aac", "-b:a", "192k"]
        else:
            command += ["-an"]
        command += ["-movflags", "+faststart", str(destination)]
        self._run(command)

    @staticmethod
    def _atempo(speed: float) -> str:
        if speed < 0.5 or speed > 2.0:
            raise ValueError("EDL speed must be between 0.5x and 2.0x.")
        return f"atempo={speed:.6f}"

    def _render_edl(
        self,
        source: Path,
        destination: Path,
        output: OutputSettings,
        edl_path: Path,
        source_probe: dict[str, Any],
        crf: int,
        preset: str,
    ) -> None:
        edl = EDLDocument.model_validate_json(edl_path.read_text(encoding="utf-8"))
        source_duration = float(source_probe.get("format", {}).get("duration", 0))
        segment_dir = destination.parent / ".segments"
        segment_dir.mkdir(parents=True, exist_ok=True)
        segment_files: list[Path] = []
        has_source_audio = self.has_audio(source_probe)

        for index, segment in enumerate(edl.segments):
            if segment.end > source_duration + 0.05:
                raise ValueError(
                    f"EDL segment {index} ends at {segment.end:.3f}s, "
                    f"past source duration {source_duration:.3f}s."
                )
            duration = segment.end - segment.start
            output_duration = duration / segment.speed
            target = segment_dir / f"segment-{index:04d}.mp4"
            video_filter = (
                f"[0:v]setpts=PTS/{segment.speed:.6f},"
                f"{self._video_filter(output)}[v]"
            )
            if has_source_audio and segment.keep_audio:
                command = [
                    self.ffmpeg_bin, "-y", "-ss", str(segment.start), "-i", str(source),
                    "-t", f"{output_duration:.6f}",
                    "-vf", f"setpts=PTS/{segment.speed:.6f},{self._video_filter(output)}",
                    "-af", self._atempo(segment.speed),
                    "-map", "0:v:0", "-map", "0:a:0",
                    "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(target),
                ]
            else:
                filter_complex = (
                    video_filter
                    + f";[1:a]atrim=duration={output_duration:.6f},"
                    + "asetpts=PTS-STARTPTS[a]"
                )
                command = [
                    self.ffmpeg_bin, "-y", "-ss", str(segment.start), "-i", str(source),
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]",
                    "-t", f"{output_duration:.6f}",
                    "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(target),
                ]
            self._run(command)
            segment_files.append(target)

        concat_file = segment_dir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{path.as_posix()}'\n" for path in segment_files),
            encoding="utf-8",
        )
        self._run(
            [
                self.ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                "-movflags", "+faststart", str(destination),
            ]
        )

    def remux_faststart(self, source: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self.ffmpeg_bin, "-y", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                "-movflags", "+faststart", str(destination),
            ]
        )
        return destination
