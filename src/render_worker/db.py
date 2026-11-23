from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_STATES = (
    "DOWNLOADING",
    "VALIDATING",
    "PREPROCESSING",
    "RENDERING",
    "QA",
    "UPLOADING",
)

ALLOWED_TRANSITIONS = {
    "QUEUED": {"DOWNLOADING", "FAILED"},
    "DOWNLOADING": {"VALIDATING", "FAILED"},
    "VALIDATING": {"PREPROCESSING", "FAILED"},
    "PREPROCESSING": {"RENDERING", "FAILED"},
    "RENDERING": {"QA", "FAILED"},
    "QA": {"UPLOADING", "FAILED"},
    "UPLOADING": {"SUCCEEDED", "FAILED"},
    "SUCCEEDED": set(),
    "FAILED": set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    drive_folder_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT,
                    output_file_id TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_state_created ON jobs(state, created_at)"
            )

    def create_job(self, job_id: str, drive_folder_id: str, manifest: dict[str, Any]) -> bool:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO jobs
                (job_id, drive_folder_id, state, manifest_json, created_at, updated_at)
                VALUES (?, ?, 'QUEUED', ?, ?, ?)
                """,
                (job_id, drive_folder_id, json.dumps(manifest), now, now),
            )
            return cursor.rowcount == 1

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def list_by_state(self, state: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE state = ? ORDER BY created_at LIMIT ?",
                (state, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def transition(self, job_id: str, new_state: str, error: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown job: {job_id}")
            current = row["state"]
            if new_state not in ALLOWED_TRANSITIONS.get(current, set()):
                raise ValueError(f"Invalid job transition: {current} -> {new_state}")
            connection.execute(
                "UPDATE jobs SET state = ?, updated_at = ?, error = ? WHERE job_id = ?",
                (new_state, utc_now(), error, job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET state = 'FAILED', updated_at = ?, error = ?
                WHERE job_id = ? AND state NOT IN ('SUCCEEDED', 'FAILED')
                """,
                (utc_now(), error[:4000], job_id),
            )

    def set_output_file(self, job_id: str, file_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET output_file_id = ?, updated_at = ? WHERE job_id = ?",
                (file_id, utc_now(), job_id),
            )

    def recover_interrupted(self) -> int:
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE jobs SET state = 'QUEUED', updated_at = ?,
                    error = 'Recovered after worker restart; job will be reprocessed.'
                WHERE state IN ({placeholders})
                """,
                (utc_now(), *ACTIVE_STATES),
            )
            return cursor.rowcount
