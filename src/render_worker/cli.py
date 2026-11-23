from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from logging.handlers import RotatingFileHandler

import requests

from .config import Settings
from .drive import DriveMailbox
from .remotion_engine import RemotionEngine
from .worker import RenderWorker


def _version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _drive_auth_method(settings: Settings) -> str | None:
    if settings.service_account_file:
        return "service_account"
    if settings.oauth_client_file:
        return "oauth"
    return None


def doctor(settings: Settings) -> dict[str, object]:
    auth_method = _drive_auth_method(settings)
    drive_ready = bool(
        settings.drive_mailbox_root_id
        and (
            (auth_method == "service_account" and settings.service_account_file.is_file())
            or (auth_method == "oauth" and settings.token_file.is_file())
        )
    )
    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "ffmpeg": _version([settings.ffmpeg_bin, "-version"]),
        "ffprobe": _version([settings.ffprobe_bin, "-version"]),
        "node": _version([settings.node_bin, "--version"]),
        "npm": _version([settings.npm_bin, "--version"]),
        "drive_auth_method": auth_method,
        "oauth_client_file": bool(settings.oauth_client_file and settings.oauth_client_file.is_file()),
        "drive_token_file": bool(settings.token_file.is_file()),
        "drive_mailbox_root_id_configured": bool(settings.drive_mailbox_root_id),
        "remote_asset_downloader": {
            "requests": requests.__version__,
            "https_only": not settings.asset_download_allow_http,
            "timeout_seconds": settings.asset_download_timeout_seconds,
            "max_bytes": settings.asset_download_max_bytes,
        },
        "remotion": RemotionEngine(settings.remotion_dir, settings.node_bin).doctor(),
    }
    remotion = checks["remotion"]
    checks["ready_for_render"] = bool(
        checks["ffmpeg"]
        and checks["ffprobe"]
        and checks["node"]
        and checks["npm"]
        and isinstance(remotion, dict)
        and remotion.get("remotion_binary")
    )
    checks["ready_for_drive"] = drive_ready
    checks["ready_for_remote_assets"] = bool(requests.__version__)
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="render-worker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local dependencies and configuration.")
    sub.add_parser("auth-drive", help="Authorize this machine with a Google user account.")
    sub.add_parser("setup-drive", help="Create the mailbox folders.")
    run = sub.add_parser("run", help="Start the polling worker.")
    run.add_argument("--once", action="store_true", help="Poll one batch, then exit.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    settings.ensure_local_dirs()
    file_handler = RotatingFileHandler(
        settings.log_dir / "worker.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
        force=True,
    )
    try:
        if args.command == "doctor":
            result = doctor(settings)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if not result["ready_for_render"]:
                raise SystemExit(2)
            return
        if args.command == "auth-drive":
            settings.validate_drive()
            drive = DriveMailbox(
                service_account_file=settings.service_account_file,
                oauth_client_file=settings.oauth_client_file,
                token_file=settings.token_file,
                allow_interactive=True,
            )
            print(f"Google Drive authentication ready ({drive.auth_method}).")
            return
        if args.command == "setup-drive":
            settings.validate_drive()
            drive = DriveMailbox(
                service_account_file=settings.service_account_file,
                oauth_client_file=settings.oauth_client_file,
                token_file=settings.token_file,
            )
            folders = drive.ensure_mailbox_folders(settings.drive_mailbox_root_id or "")
            print(json.dumps(folders, indent=2))
            return
        if args.command == "run":
            worker = RenderWorker(settings)
            if args.once:
                print(f"Processed jobs: {worker.run_once()}")
            else:
                worker.run_forever()
    except KeyboardInterrupt:
        print("Worker stopped.")
    except Exception as exc:
        logging.exception("Command failed")
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
