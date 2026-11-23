from pathlib import Path
from unittest.mock import Mock

import pytest

from render_worker.models import AssetManifest, JobManifest, TimelineDocument
from render_worker.remote_assets import DownloadedAsset
from render_worker.worker import RenderWorker


def downloaded(asset_id: str, kind: str, media_type: str, tmp_path: Path):
    path = tmp_path / (asset_id + (".gif" if media_type == "gif" else ".mp4"))
    path.write_bytes(b"test-asset")
    return DownloadedAsset(
        asset_id=asset_id,
        kind=kind,
        local_path=path,
        media_type=media_type,
        mime_type="application/octet-stream",
        size_bytes=path.stat().st_size,
        sha256="a" * 64,
        source_host="cdn.example.test",
        resolved_url="https://cdn.example.test/" + path.name,
    )


def test_worker_loads_drive_asset_manifest_and_downloads_remote_assets(tmp_path):
    manifest_path = tmp_path / "asset_manifest.json"
    manifest_path.write_text(
        """
        {
          "schema_version": "1.0",
          "assets": [
            {"id": "reaction", "kind": "meme", "url": "https://cdn.example.test/reaction.gif"}
          ]
        }
        """,
        encoding="utf-8",
    )
    manifest = JobManifest.model_validate(
        {
            "job_id": "remote-assets-001",
            "input": {
                "source_video": "source.mp4",
                "asset_manifest": "asset_manifest.json",
            },
        }
    )
    worker = RenderWorker.__new__(RenderWorker)
    asset = downloaded("reaction", "meme", "gif", tmp_path)
    worker.asset_downloader = Mock(
        download_all=Mock(
            return_value=(
                {"reaction": asset},
                [{"id": "reaction", "kind": "meme", "status": "VERIFIED"}],
            )
        )
    )

    asset_manifest, assets, report = worker._download_remote_assets(tmp_path, manifest)

    assert isinstance(asset_manifest, AssetManifest)
    assert assets["reaction"].media_type == "gif"
    assert report[0]["status"] == "VERIFIED"
    worker.asset_downloader.download_all.assert_called_once()


def test_worker_accepts_meme_and_broll_asset_references(tmp_path):
    assets = {
        "reaction": downloaded("reaction", "meme", "gif", tmp_path),
        "kitchen": downloaded("kitchen", "broll", "video", tmp_path),
    }
    timeline = TimelineDocument.model_validate(
        {
            "schema_version": "1.0",
            "layers": [
                {
                    "id": "meme",
                    "type": "meme",
                    "asset_id": "reaction",
                    "start": 1,
                    "end": 2,
                },
                {
                    "id": "broll",
                    "type": "broll",
                    "asset_id": "kitchen",
                    "start": 3,
                    "end": 4,
                },
            ],
        }
    )

    RenderWorker._validate_timeline_assets(timeline, assets)


def test_worker_rejects_timeline_asset_id_that_was_not_downloaded():
    timeline = TimelineDocument.model_validate(
        {
            "layers": [
                {
                    "id": "missing-meme",
                    "type": "meme",
                    "asset_id": "not-downloaded",
                    "start": 1,
                    "end": 2,
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="missing or failed asset"):
        RenderWorker._validate_timeline_assets(timeline, {})


def test_worker_rejects_non_video_asset_for_broll(tmp_path):
    image_asset = downloaded("still", "meme", "image", tmp_path)
    timeline = TimelineDocument.model_validate(
        {
            "layers": [
                {
                    "id": "bad-broll",
                    "type": "broll",
                    "asset_id": "still",
                    "start": 1,
                    "end": 2,
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="must reference a video"):
        RenderWorker._validate_timeline_assets(timeline, {"still": image_asset})
