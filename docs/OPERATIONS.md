# Operations

## Install

The bootstrap script installs the Python package and Remotion npm dependencies. It checks for Node.js 20+ and FFmpeg/FFprobe; it does not install or change the NVIDIA driver.

~~~bash
./scripts/bootstrap_ubuntu.sh
cp .env.example .env
nano .env
source .venv/bin/activate
render-worker auth-drive
render-worker setup-drive
render-worker doctor
~~~

Complete auth-drive once before enabling the systemd service. The OAuth token is refreshed automatically and saved locally.

## Run one polling cycle

~~~bash
render-worker run --once
~~~

The command handles at most WORKER_MAX_JOBS_PER_POLL jobs and exits. Use this first to validate Drive permissions and the render environment.

## Run continuously

~~~bash
render-worker run
~~~

Default polling interval is 15 seconds. Set WORKER_POLL_INTERVAL_SECONDS to change it. The worker runs one job at a time and holds a host-level lock to prevent a second local process from competing for the mailbox.

## Logs

Logs are written to both stdout and var/logs/worker.log. The local log rotates at 10 MB and keeps five backups. Under systemd, follow the journal with journalctl as well.

## systemd

Copy systemd/render-worker.service to /etc/systemd/system/render-worker.service and adjust User, WorkingDirectory, and EnvironmentFile for the target machine.

~~~bash
sudo systemctl daemon-reload
sudo systemctl enable --now render-worker
sudo journalctl -u render-worker -f
~~~

Do not run a second worker against the same mailbox. This milestone uses a single-host lock, not a distributed lease.

## Troubleshooting

- OAuth error: verify the OAuth consent screen, test-user list, Desktop client JSON, and local port-forward on 8765.
- Drive permission error: confirm the OAuth user owns or can edit the mailbox folder; for service accounts, confirm the folder is in a Shared Drive.
- No jobs found: check that the job folder is directly inside inbox and contains job.json.
- Remotion not installed: run cd remotion && npm install.
- Font fallback: install Be Vietnam Pro or Noto Sans on Ubuntu and rerun the render.
- Failed job: inspect var/logs/worker.log, outputs/<job_id>/status-failed.json, and the input folder in failed.
- Interrupted job: restart the worker; active SQLite jobs are re-queued and downloaded again from processing.

## Output contract

A successful output must be H.264, yuv420p, requested dimensions and FPS, AAC when the source had audio, and decode fully with FFmpeg. Automated QA does not replace a human review of faces, safe zones, captions, crop, pacing, or story accuracy.
