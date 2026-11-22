import pytest
from pydantic import ValidationError

from render_worker.models import JobManifest


def valid_job():
    return {
        "schema_version": "1.0",
        "job_id": "demo-001",
        "input": {"source_video": "assets/source.mp4", "edl": "edl.json"},
    }


def test_valid_job_uses_vertical_defaults():
    job = JobManifest.model_validate(valid_job())
    assert job.output.width == 1080
    assert job.output.height == 1920
    assert job.output.fps == 30


@pytest.mark.parametrize(
    "input_data",
    [
        {"source_video": "../secret.mp4"},
        {"source_video": "/tmp/source.mp4"},
        {"source_video": "C:\\\\temp\\\\source.mp4"},
        {"source_video": "assets/source.mp4", "base_video": "assets/base.mp4"},
        {"base_video": "assets/base.mp4", "edl": "edl.json"},
    ],
)
def test_rejects_unsafe_or_ambiguous_input(input_data):
    data = valid_job()
    data["input"] = input_data
    with pytest.raises(ValidationError):
        JobManifest.model_validate(data)
