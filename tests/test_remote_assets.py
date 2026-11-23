import hashlib
import socket
from unittest.mock import Mock

import pytest

from render_worker.models import AssetManifest, RemoteAssetSpec, TimelineDocument
from render_worker.remote_assets import (
    AssetDownloadError,
    RemoteAssetDownloader,
    validate_download_url,
)


class FakeResponse:
    def __init__(self, body: bytes, status_code: int = 200, headers: dict | None = None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self.body), max(1, min(chunk_size, 7))):
            yield self.body[offset : offset + max(1, min(chunk_size, 7))]

    def close(self):
        self.closed = True


def mock_public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ],
    )


def wav_bytes():
    return b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"fmt " + b"\x00" * 32


def test_downloads_and_hash_verifies_direct_audio_url(tmp_path, monkeypatch):
    mock_public_dns(monkeypatch)
    payload = wav_bytes()
    response = FakeResponse(
        payload,
        headers={"Content-Type": "audio/wav", "Content-Length": str(len(payload))},
    )
    session_get = Mock(return_value=response)
    monkeypatch.setattr("requests.Session.get", session_get)
    spec = RemoteAssetSpec(
        id="sfx-impact",
        kind="sfx",
        url="https://cdn.example.test/audio/impact.wav?download=1",
        sha256=hashlib.sha256(payload).hexdigest(),
    )

    asset = RemoteAssetDownloader().download(spec, tmp_path)

    assert asset.local_path.name == "sfx-impact.wav"
    assert asset.local_path.read_bytes() == payload
    assert asset.media_type == "audio"
    assert asset.sha256 == hashlib.sha256(payload).hexdigest()
    assert "?" not in asset.resolved_url
    session_get.assert_called_once()


def test_blocks_localhost_and_private_ip_before_request():
    with pytest.raises(AssetDownloadError, match="Blocked local"):
        validate_download_url("https://localhost/private.mp3")
    with pytest.raises(AssetDownloadError, match="non-public"):
        validate_download_url("https://127.0.0.1/private.mp3")


def test_revalidates_redirect_target_before_following(tmp_path, monkeypatch):
    mock_public_dns(monkeypatch)
    response = FakeResponse(
        b"",
        status_code=302,
        headers={"Location": "https://127.0.0.1/private"},
    )
    session_get = Mock(return_value=response)
    monkeypatch.setattr("requests.Session.get", session_get)
    spec = RemoteAssetSpec(
        id="sfx-redirect",
        kind="sfx",
        url="https://cdn.example.test/redirect",
    )

    with pytest.raises(AssetDownloadError, match="non-public"):
        RemoteAssetDownloader().download(spec, tmp_path)

    session_get.assert_called_once()


def test_rejects_download_larger_than_limit(tmp_path, monkeypatch):
    mock_public_dns(monkeypatch)
    payload = wav_bytes()
    response = FakeResponse(
        payload,
        headers={"Content-Type": "audio/wav", "Content-Length": str(len(payload))},
    )
    monkeypatch.setattr("requests.Session.get", Mock(return_value=response))
    spec = RemoteAssetSpec(id="large-sfx", kind="sfx", url="https://cdn.example.test/a.wav")

    with pytest.raises(AssetDownloadError, match="download limit"):
        RemoteAssetDownloader(max_bytes=10).download(spec, tmp_path)


def test_rejects_html_preview_page_instead_of_media_file(tmp_path, monkeypatch):
    mock_public_dns(monkeypatch)
    response = FakeResponse(
        b"<!doctype html><html><body>preview page</body></html>",
        headers={"Content-Type": "text/html"},
    )
    monkeypatch.setattr("requests.Session.get", Mock(return_value=response))
    spec = RemoteAssetSpec(
        id="music-preview",
        kind="music",
        url="https://example.test/track",
    )

    with pytest.raises(AssetDownloadError, match="recognizable media"):
        RemoteAssetDownloader().download(spec, tmp_path)


def test_asset_manifest_rejects_duplicate_ids_and_invalid_timeline_refs():
    with pytest.raises(ValueError, match="unique"):
        AssetManifest.model_validate(
            {
                "assets": [
                    {"id": "same", "kind": "sfx", "url": "https://cdn.example.test/a.wav"},
                    {"id": "same", "kind": "music", "url": "https://cdn.example.test/b.mp3"},
                ]
            }
        )

    with pytest.raises(ValueError, match="requires asset_id"):
        TimelineDocument.model_validate(
            {
                "layers": [
                    {"id": "meme", "type": "meme", "start": 0, "end": 1}
                ]
            }
        )


def test_asset_audio_mix_settings_validate_timing():
    with pytest.raises(ValueError, match="fade durations"):
        RemoteAssetSpec(
            id="music-long-fade",
            kind="music",
            url="https://cdn.example.test/music.mp3",
            start=0,
            end=1,
            fade_in=0.8,
            fade_out=0.8,
        )
