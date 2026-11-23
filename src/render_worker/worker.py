from __future__ import annotations

import fcntl
import json
import logging
import shutil
import time
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Iterator

from pydantic import ValidationError

from .config import Settings
from .db import JobStore
from .drive import DriveMailbox
from .ffmpeg_engine import FFmpegEngine
from .models import AssetManifest, JobManifest, TimelineDocument
from .qa import validate_output
from .remote_assets import AssetDownloadError, DownloadedAsset, RemoteAssetDownloader
from .remotion_engine import RemotionEngine


logger = logging.getLogger("render_worker")


class RenderWorker:
    def __init__(self, settings: Settings):
        settings.validate_drive()
        settings.ensure_local_dirs()
        self.settings = settings
        self.drive = DriveMailbox(
            service_account_file=settings.service_account_file,
            oauth_client_file=settings.oauth_client_file,
            token_file=settings.token_file,
        )
        self.store = JobStore(settings.database_path)
        self.ffmpeg = FFmpegEngine(settings.ffmpeg_bin, settings.ffprobe_bin)
        self.remotion = RemotionEngine(settings.remotion_dir, settings.node_bin)
        self.asset_downloader = RemoteAssetDownloader(
            timeout_seconds=settings.asset_download_timeout_seconds,
            max_bytes=settings.asset_download_max_bytes,
            allow_http=settings.asset_download_allow_http,
        )
        self.folders = self.drive.ensure_mailbox_folders(settings.drive_mailbox_root_id or "")

    @contextmanager
    def _worker_lock(self) -> Iterator[None]:
        lock_path = self.settings.work_dir / ".worker.lock"
        handle = lock_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise RuntimeError("Another local worker process already holds the mailbox lock.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def run_forever(self) -> None:
        logger.info("Worker started. Poll interval: %ss", self.settings.poll_interval_seconds)
        with self._worker_lock():
            while True:
                self._run_once()
                time.sleep(self.settings.poll_interval_seconds)

    def run_once(self) -> int:
        with self._worker_lock():
            return self._run_once()

    def _run_once(self) -> int:
        recovered = self.store.recover_interrupted()
        if recovered:
            logger.warning("Recovered %s interrupted job(s); they will be reprocessed.", recovered)

        processed = 0
        queued = self.store.list_by_state("QUEUED", self.settings.max_jobs_per_poll)
        for row in queued:
            self._process_job(row["job_id"], row["drive_folder_id"])
            processed += 1

        remaining = max(0, self.settings.max_jobs_per_poll - processed)
        if remaining:
            inbox = self.drive.list_inbox_folders(self.folders["inbox"])
            for folder in inbox:
                if self._accept_and_process(folder):
                    processed += 1
                if processed >= self.settings.max_jobs_per_poll:
                    break
        return processed

    def _accept_and_process(self, folder: dict[str, Any]) -> bool:
        folder_id = folder["id"]
        folder_name = folder.get("name", folder_id)
        try:
            raw_manifest = self.drive.read_json_child(folder_id, "job.json")
            manifest = JobManifest.model_validate(raw_manifest)
        except FileNotFoundError:
            logger.info("Waiting for job.json in Drive job folder %s", folder_name)
            return False
        except (ValueError, ValidationError, json.JSONDecodeError):
            logger.exception("Rejecting malformed Drive job folder %s", folder_name)
            self.drive.move_folder(folder_id, self.folders["failed"])
            return True

        existing = self.store.get_job(manifest.job_id)
        if existing:
            logger.error(
                "Duplicate job_id %s in Drive folder %s; moving duplicate to failed.",
                manifest.job_id,
                folder_name,
            )
            self.drive.move_folder(folder_id, self.folders["failed"])
            return True

        self.drive.move_folder(folder_id, self.folders["processing"])
        self.store.create_job(manifest.job_id, folder_id, manifest.model_dump(mode="json"))
        self._process_job(manifest.job_id, folder_id)
        return True

    def _download_remote_assets(
        self, workspace: Any, manifest: JobManifest
    ) -> tuple[AssetManifest, dict[str, DownloadedAsset], list[dict[str, object]]]:
        asset_manifest = AssetManifest()
        if not manifest.input.asset_manifest:
            return asset_manifest, {}, []

        manifest_path = workspace / manifest.input.asset_manifest
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Asset manifest not found: {manifest.input.asset_manifest}")
        asset_manifest = AssetManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8-sig")
        )
        assets_dir = workspace / "remote_assets"
        downloaded, report = self.asset_downloader.download_all(asset_manifest, assets_dir)

        verified: dict[str, DownloadedAsset] = {}
        specs = {asset.id: asset for asset in asset_manifest.assets}
        for asset_id, asset in downloaded.items():
            spec = specs[asset_id]
            if asset.media_type in ("image", "gif"):
                if spec.kind not in ("meme",):
                    raise AssetDownloadError(
                        f"Asset '{asset_id}' is an image but kind is '{spec.kind}'."
                    )
                verified[asset_id] = asset
                continue

            probe = self.ffmpeg.probe(asset.local_path)
            streams = probe.get("streams", [])
            has_video = any(stream.get("codec_type") == "video" for stream in streams)
            has_audio = any(stream.get("codec_type") == "audio" for stream in streams)

            if spec.kind in ("music", "sfx"):
                if not has_audio or has_video:
                    raise AssetDownloadError(
                        f"Audio asset '{asset_id}' must contain an audio stream and no video stream."
                    )
                verified[asset_id] = replace(asset, media_type="audio")
            elif spec.kind == "broll":
                if not has_video:
                    raise AssetDownloadError(f"B-roll asset '{asset_id}' has no video stream.")
                verified[asset_id] = replace(asset, media_type="video")
            elif spec.kind == "meme":
                if not has_video:
                    raise AssetDownloadError(
                        f"Meme asset '{asset_id}' must be an image, GIF, or video."
                    )
                verified[asset_id] = replace(
                    asset,
                    media_type="gif" if asset.local_path.suffix.lower() == ".gif" else "video",
                )

        return asset_manifest, verified, report

    @staticmethod
    def _validate_timeline_assets(
        timeline: TimelineDocument, assets: dict[str, DownloadedAsset]
    ) -> None:
        for cue in timeline.layers:
            if cue.type not in ("meme", "broll"):
                continue
            asset = assets.get(cue.asset_id or "")
            if not asset:
                raise ValueError(
                    f"Timeline cue '{cue.id}' references missing or failed asset '{cue.asset_id}'."
                )
            if cue.type == "broll" and asset.media_type != "video":
                raise ValueError(f"B-roll cue '{cue.id}' must reference a video asset.")
            if cue.type == "meme" and asset.media_type not in ("image", "gif", "video"):
                raise ValueError(f"Meme cue '{cue.id}' references unsupported media.")

    def _process_job(self, job_id: str, drive_folder_id: str) -> None:
        workspace = self.settings.work_dir / job_id
        try:
            if workspace.exists():
                shutil.rmtree(workspace)
            workspace.mkdir(parents=True, exist_ok=True)
            self.store.transition(job_id, "DOWNLOADING")
            self.drive.download_folder_recursive(drive_folder_id, workspace)

            manifest_path = workspace / "job.json"
            manifest = JobManifest.model_validate_json(manifest_path.read_text(encoding="utf-8-sig"))
            if manifest.job_id != job_id:
                raise ValueError("job.json job_id changed after the folder was claimed.")

            asset_manifest, downloaded_assets, asset_report = self._download_remote_assets(
                workspace, manifest
            )

            self.store.transition(job_id, "VALIDATING")
            input_name = manifest.input.source_video or manifest.input.base_video
            source = workspace / str(input_name)
            if not source.is_file():
                raise FileNotFoundError(f"Manifest input file does not exist: {input_name}")

            source_probe = self.ffmpeg.probe(source)
            source_has_audio = self.ffmpeg.has_audio(source_probe)
            edl_path = workspace / manifest.input.edl if manifest.input.edl else None
            if edl_path and not edl_path.is_file():
                raise FileNotFoundError(f"EDL file not found: {manifest.input.edl}")

            self.store.transition(job_id, "PREPROCESSING")
            base_video = workspace / "base.mp4"
            self.ffmpeg.prepare_base(
                source,
                base_video,
                manifest.output,
                edl_path=edl_path,
                crf=manifest.render.crf,
                preset=manifest.render.preset,
            )
            base_probe = self.ffmpeg.probe(base_video)
            base_duration = float(base_probe.get("format", {}).get("duration", 0))
            if base_duration <= 0:
                raise ValueError("Preprocessed base video has no valid duration.")

            timeline = TimelineDocument(layers=[])
            if manifest.input.timeline:
                timeline_path = workspace / manifest.input.timeline
                if not timeline_path.is_file():
                    raise FileNotFoundError(f"Timeline file not found: {manifest.input.timeline}")
                timeline = TimelineDocument.model_validate_json(
                    timeline_path.read_text(encoding="utf-8-sig")
                )
            self._validate_timeline_assets(timeline, downloaded_assets)

            self.store.transition(job_id, "RENDERING")
            remotion_output = workspace / "remotion-render.mp4"
            self.remotion.render(
                job_id=job_id,
                base_video=base_video,
                timeline=timeline,
                output_path=remotion_output,
                manifest=manifest,
                duration_seconds=base_duration,
                assets=downloaded_assets,
                asset_manifest=asset_manifest,
            )

            self.store.transition(job_id, "QA")
            final_output = workspace / "output.mp4"
            self.ffmpeg.remux_faststart(remotion_output, final_output)
            base_has_audio = self.ffmpeg.has_audio(base_probe)
            has_remote_audio = any(
                asset.kind in ("music", "sfx") for asset in downloaded_assets.values()
            )
            report = validate_output(
                final_output,
                self.settings.ffmpeg_bin,
                self.settings.ffprobe_bin,
                manifest.output,
                require_audio=(source_has_audio and base_has_audio) or has_remote_audio,
                expected_duration=base_duration,
            )
            report["job_id"] = job_id
            report["title"] = manifest.title
            report["render_engine"] = "Remotion"
            report["preprocessor"] = "FFmpeg"
            report["remote_assets"] = asset_report
            report_path = workspace / "qa.json"
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if not report["passed"]:
                raise RuntimeError("QA failed: " + "; ".join(report["errors"]))

            self.store.transition(job_id, "UPLOADING")
            output_folder = self.drive.ensure_folder(self.folders["outputs"], job_id)
            uploaded = self.drive.upload_file(final_output, output_folder, "output.mp4")
            self.store.set_output_file(job_id, uploaded["id"])
            self.drive.upload_file(report_path, output_folder, "qa.json", "application/json")
            status = {
                "job_id": job_id,
                "state": "SUCCEEDED",
                "output_file_id": uploaded["id"],
                "output_url": uploaded.get("webViewLink"),
                "qa_passed": True,
                "remote_assets_verified": len(downloaded_assets),
            }
            self.drive.upload_json(status, output_folder, "status.json")
            self.drive.move_folder(drive_folder_id, self.folders["completed"])
            self.store.transition(job_id, "SUCCEEDED")
            logger.info("Job %s completed. Output Drive file: %s", job_id, uploaded["id"])
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            self.store.fail(job_id, str(exc))
            try:
                status = {"job_id": job_id, "state": "FAILED", "error": str(exc)[:3000]}
                output_folder = self.drive.ensure_folder(self.folders["outputs"], job_id)
                self.drive.upload_json(status, output_folder, "status-failed.json")
                self.drive.move_folder(drive_folder_id, self.folders["failed"])
            except Exception:
                logger.exception("Could not publish failure status for job %s", job_id)
