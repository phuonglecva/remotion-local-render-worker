from render_worker.models import decode_json_bytes, read_json_text


def test_decode_json_bytes_accepts_utf8_bom():
    payload = b'\\xef\\xbb\\xbf{"ok": true}'
    assert decode_json_bytes(payload) == '{"ok": true}'


def test_read_json_text_accepts_utf8_bom(tmp_path):
    path = tmp_path / "job.json"
    path.write_bytes(b'\\xef\\xbb\\xbf{"job_id": "bom-safe"}')
    assert read_json_text(path) == '{"job_id": "bom-safe"}'
