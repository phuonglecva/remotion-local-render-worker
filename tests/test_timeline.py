import pytest
from pydantic import ValidationError

from render_worker.models import TimelineDocument


def test_timeline_accepts_caption_zoom_and_bubble():
    timeline = TimelineDocument.model_validate(
        {
            "schema_version": "1.0",
            "layers": [
                {"id": "hook", "type": "caption", "start": 0, "end": 2, "text": "Ôi trời!"},
                {"id": "zoom", "type": "zoom", "start": 2, "end": 3, "scale": 1.1},
                {"id": "bubble", "type": "bubble", "start": 3, "end": 5, "text": "Đến lượt em!"},
            ],
        }
    )
    assert len(timeline.layers) == 3


def test_timeline_requires_text_for_caption():
    with pytest.raises(ValidationError):
        TimelineDocument.model_validate(
            {"schema_version": "1.0", "layers": [
                {"id": "bad", "type": "caption", "start": 0, "end": 1}
            ]}
        )
