from render_worker.models import decode_json_bytes, read_json_text


def test_decode_json_bytes_accepts_utf8_bom():
    payload = bytes.fromhex("efbbbf") + b'{"ok": true}'
    assert decode_json_bytes(payload) == '{"ok": true}'


def test_read_json_text_accepts_utf8_bom(tmp_path):
    path = tmp_path / "job.json"
    path.write_bytes(bytes.fromhex("efbbbf") + b'{"job_id": "bom-safe"}')
    assert read_json_text(path) == '{"job_id": "bom-safe"}'
