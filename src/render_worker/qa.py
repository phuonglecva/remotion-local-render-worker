from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .models import OutputSettings


def _rate(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return None


def validate_output(
    path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    expected: OutputSettings,
    require_audio: bool,
    expected_duration: float | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if not path.is_file():
        return {"passed": False, "errors": ["Output file does not exist."], "path": str(path)}
    size = path.stat().st_size
    if size < 1024:
        errors.append("Output file is unexpectedly small.")

    probe_run = subprocess.run(
        [ffprobe_bin, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if probe_run.returncode != 0:
        errors.append("ffprobe could not inspect the output: " + probe_run.stderr[-1500:])
        return {"passed": False, "errors": errors, "path": str(path), "size_bytes": size}

    probe = json.loads(probe_run.stdout)
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(probe.get("format", {}).get("duration", 0) or 0)

    if not video:
        errors.append("No video stream found.")
    else:
        if video.get("codec_name") != "h264":
            errors.append(f"Expected H.264, got {video.get('codec_name')}.")
        if video.get("pix_fmt") != "yuv420p":
            errors.append(f"Expected yuv420p, got {video.get('pix_fmt')}.")
        if int(video.get("width", 0)) != expected.width:
            errors.append(f"Expected width {expected.width}, got {video.get('width')}.")
        if int(video.get("height", 0)) != expected.height:
            errors.append(f"Expected height {expected.height}, got {video.get('height')}.")
        actual_fps = _rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
        if actual_fps is None or abs(actual_fps - expected.fps) > 0.05:
            errors.append(f"Expected {expected.fps} FPS, got {actual_fps}.")

    if require_audio and not audio:
        errors.append("Source audio was required but output has no audio stream.")
    if audio and audio.get("codec_name") != "aac":
        errors.append(f"Expected AAC audio, got {audio.get('codec_name')}.")
    if duration <= 0:
        errors.append("Output duration is zero or unavailable.")
    if expected_duration and abs(duration - expected_duration) > max(0.5, 2 / expected.fps):
        errors.append(
            f"Duration drift is too large: expected {expected_duration:.3f}s, got {duration:.3f}s."
        )

    decode = subprocess.run(
        [ffmpeg_bin, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    if decode.returncode != 0:
        errors.append("Full-file FFmpeg decode failed: " + decode.stderr[-2000:])

    return {
        "passed": not errors,
        "errors": errors,
        "path": str(path),
        "size_bytes": size,
        "duration_seconds": duration,
        "video": {
            "codec": video.get("codec_name") if video else None,
            "width": video.get("width") if video else None,
            "height": video.get("height") if video else None,
            "pixel_format": video.get("pix_fmt") if video else None,
            "fps": _rate(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else None,
        },
        "audio": {
            "codec": audio.get("codec_name") if audio else None,
            "sample_rate": audio.get("sample_rate") if audio else None,
            "channels": audio.get("channels") if audio else None,
        } if audio else None,
        "full_decode": "passed" if decode.returncode == 0 else "failed",
    }
