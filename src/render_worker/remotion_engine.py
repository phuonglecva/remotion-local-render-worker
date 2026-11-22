from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import JobManifest, TimelineDocument


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
    ) -> Path:
        status = self.doctor()
        if not all(status.values()):
            raise RemotionError(
                "Remotion dependencies are not installed. Run: cd remotion && npm install"
            )

        fps = manifest.output.fps
        duration_frames = max(1, round(duration_seconds * fps))
        public_job_dir = self.remotion_dir / "public" / "jobs" / job_id
        public_job_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_video, public_job_dir / "base.mp4")

        props = {
            "baseVideoPath": f"jobs/{job_id}/base.mp4",
            "durationInFrames": duration_frames,
            "fps": fps,
            "width": manifest.output.width,
            "height": manifest.output.height,
            "timeline": timeline.model_dump(mode="json"),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        props_path = output_path.parent / "remotion-props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

        command = [
            "npx", "--no-install", "remotion", "render",
            "src/index.ts", "Main", str(output_path),
            f"--props-file={props_path}",
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
