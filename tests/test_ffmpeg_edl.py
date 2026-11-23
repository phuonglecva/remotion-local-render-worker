import json
import shutil
import subprocess

import pytest

from render_worker.ffmpeg_engine import FFmpegEngine
from render_worker.models import OutputSettings


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and FFprobe are required for the media integration test.",
)
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_edl_speed_ramp_creates_valid_concatenated_base(tmp_path, encoding):
    source = tmp_path / "source.mp4"
    edl = tmp_path / "edl.json"
    output = tmp_path / "base.mp4"

    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(source),
        ],
        check=True,
        capture_output=True,
    )
    edl.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "segments": [
                    {"start": 0, "end": 1, "speed": 1.0, "keep_audio": True},
                    {"start": 1, "end": 2, "speed": 2.0, "keep_audio": True},
                ],
            }
        ),
        encoding=encoding,
    )

    engine = FFmpegEngine()
    engine.prepare_base(
        source,
        output,
        OutputSettings(width=360, height=640, fps=30),
        edl_path=edl,
        crf=28,
        preset="ultrafast",
    )
    probe = engine.probe(output)
    duration = float(probe["format"]["duration"])
    streams = probe["streams"]

    assert output.is_file() and output.stat().st_size > 1024
    assert abs(duration - 1.5) < 0.12
    assert any(stream.get("codec_type") == "video" for stream in streams)
    assert any(stream.get("codec_type") == "audio" for stream in streams)
