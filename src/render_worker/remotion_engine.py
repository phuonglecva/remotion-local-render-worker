from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import AssetManifest, JobManifest, TimelineDocument
from .remote_assets import DownloadedAsset


class RemotionError(RuntimeError):
    pass


class RemotionEngine:
    def __init__(self, remotion_dir: Path, node_bin: str = "node"):
        self.remotion_dir = remotion_dir
        self.node_bin = node_bin

    def doctor(self) -> dict[str, Any]:
        package = self.remotion_dir / "package.json"
        binary = self.remotion_dir / "node_modules" / ".bin" / "remotion"
        return {
            "package_json": package.is_file(),
            "node_modules": (self.remotion_dir / "node_modules").is_dir(),
            "remotion_binary": binary.exists(),
        }

    def render(
        self,
        job_id: str,
        base_video: Path,
        timeline: TimelineDocument,
        output_path: Path,
        manifest: JobManifest,
        duration_seconds: float,
        assets: dict[str, DownloadedAsset] | None = None,
        asset_manifest: AssetManifest | None = None,
    ) -> Path:
        status = self.doctor()
        if not all(status.values()):
            raise RemotionError(
                "Remotion dependencies are not installed. Run: cd remotion && npm install"
            )

        assets = assets or {}
        asset_manifest = asset_manifest or AssetManifest()
        fps = manifest.output.fps
        duration_frames = max(1, round(duration_seconds * fps))
        public_job_dir = self.remotion_dir / "public" / "jobs" / job_id
        public_asset_dir = public_job_dir / "assets"
        public_asset_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_video, public_job_dir / "base.mp4")

        asset_props: dict[str, dict[str, str]] = {}
        for asset_id, asset in assets.items():
            target = public_asset_dir / asset.local_path.name
            shutil.copy2(asset.local_path, target)
            asset_props[asset_id] = {
                "src": f"jobs/{job_id}/assets/{target.name}",
                "mediaType": asset.media_type,
            }

        audio_tracks: list[dict[str, Any]] = []
        for spec in asset_manifest.assets:
            if spec.kind not in ("music", "sfx") or spec.id not in asset_props:
                continue
            start = min(spec.start, duration_seconds)
            end = min(spec.end if spec.end is not None else duration_seconds, duration_seconds)
            if end <= start:
                raise RemotionError(
                    f"Audio asset '{spec.id}' has no remaining duration in the output timeline."
                )
            audio_tracks.append({
                "id": spec.id,
                "src": asset_props[spec.id]["src"],
                "start": start,
                "end": end,
                "volume": spec.volume if spec.volume is not None else (
                    0.16 if spec.kind == "music" else 0.72
                ),
                "fadeIn": spec.fade_in,
                "fadeOut": spec.fade_out,
                "loop": spec.loop,
                "duckingRanges": [item.model_dump(mode="json") for item in spec.ducking_ranges],
            })

        props = {
            "baseVideoPath": f"jobs/{job_id}/base.mp4",
            "durationInFrames": duration_frames,
            "fps": fps,
            "width": manifest.output.width,
            "height": manifest.output.height,
            "timeline": timeline.model_dump(mode="json"),
            "assets": asset_props,
            "audioTracks": audio_tracks,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        props_path = output_path.parent / "remotion-props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

        command = [
            "npx", "--no-install", "remotion", "render",
            "src/index.ts", "Main", str(output_path),
            f"--props={props_path}",
            "--codec=h264", "--pixel-format=yuv420p", "--audio-codec=aac",
            f"--crf={manifest.render.crf}",
            f"--concurrency={manifest.render.concurrency}",
        ]
        try:
            result = subprocess.run(
                command, cwd=self.remotion_dir, capture_output=True, text=True
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout)[-6000:]
                raise RemotionError(f"Remotion render failed ({result.returncode}): {detail}")
        finally:
            shutil.rmtree(public_job_dir, ignore_errors=True)

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RemotionError("Remotion exited successfully but did not create an output file.")
        return output_path
