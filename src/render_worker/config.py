from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    service_account_file: Path | None
    oauth_client_file: Path | None
    token_file: Path
    drive_mailbox_root_id: str | None
    database_path: Path
    work_dir: Path
    log_dir: Path
    remotion_dir: Path
    ffmpeg_bin: str
    ffprobe_bin: str
    node_bin: str
    npm_bin: str
    poll_interval_seconds: int
    max_jobs_per_poll: int

    @classmethod
    def from_env(cls, root_dir: Path | None = None) -> "Settings":
        root = (root_dir or Path.cwd()).resolve()
        load_dotenv(root / ".env")

        def path_value(name: str, default: str) -> Path:
            value = Path(os.getenv(name, default)).expanduser()
            return value if value.is_absolute() else (root / value).resolve()

        service_account = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        oauth_client = os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "").strip()
        mailbox_id = os.getenv("DRIVE_MAILBOX_ROOT_ID", "").strip()
        return cls(
            root_dir=root,
            service_account_file=Path(service_account).expanduser().resolve()
            if service_account
            else None,
            oauth_client_file=Path(oauth_client).expanduser().resolve() if oauth_client else None,
            token_file=path_value("GOOGLE_TOKEN_FILE", "var/google-token.json"),
            drive_mailbox_root_id=mailbox_id or None,
            database_path=path_value("WORKER_DATABASE", "var/worker.sqlite3"),
            work_dir=path_value("WORKER_WORK_DIR", "var/work"),
            log_dir=path_value("WORKER_LOG_DIR", "var/logs"),
            remotion_dir=path_value("REMOTION_DIR", "remotion"),
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg"),
            ffprobe_bin=os.getenv("FFPROBE_BIN", "ffprobe"),
            node_bin=os.getenv("NODE_BIN", "node"),
            npm_bin=os.getenv("NPM_BIN", "npm"),
            poll_interval_seconds=max(3, int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "15"))),
            max_jobs_per_poll=max(1, int(os.getenv("WORKER_MAX_JOBS_PER_POLL", "2"))),
        )

    def validate_drive(self) -> None:
        missing = []
        if self.service_account_file:
            if not self.service_account_file.is_file():
                missing.append(f"service-account file not found: {self.service_account_file}")
        elif self.oauth_client_file:
            if not self.oauth_client_file.is_file():
                missing.append(f"OAuth client file not found: {self.oauth_client_file}")
        else:
            missing.append("configure GOOGLE_OAUTH_CLIENT_FILE or GOOGLE_SERVICE_ACCOUNT_FILE")
        if not self.drive_mailbox_root_id:
            missing.append("DRIVE_MAILBOX_ROOT_ID")
        if missing:
            raise ValueError("Drive configuration is incomplete: " + ", ".join(missing))

    def ensure_local_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
