# Operations

## Install

The bootstrap script installs the Python package (including requests for remote media downloads) and Remotion npm dependencies. It checks for Node.js 20+ and FFmpeg/FFprobe; it does not install or change the NVIDIA driver.

~~~bash
./scripts/bootstrap_ubuntu.sh
cp .env.example .env
nano .env
source .venv/bin/activate
render-worker auth-drive
render-worker setup-drive
render-worker doctor
~~~

Complete auth-drive once before starting the worker with PM2. The OAuth token is refreshed automatically and saved locally. Run PM2 as the same Ubuntu user that completed Drive authorization, with access to the repository and var directory.

## Remote asset download configuration

The worker downloads music, SFX, memes/GIFs and B-roll URLs from asset_manifest.json after it downloads the job folder from Drive.

~~~env
ASSET_DOWNLOAD_TIMEOUT_SECONDS=30
ASSET_DOWNLOAD_MAX_BYTES=536870912
ASSET_DOWNLOAD_ALLOW_HTTP=false
~~~

- HTTPS is required by default. Keep HTTP disabled unless a specific trusted source requires it.
- The global download cap defaults to 512 MiB. Per-kind defaults are 100 MiB for music, 25 MiB for SFX, 100 MiB for memes and 512 MiB for B-roll.
- The downloader validates public DNS/IP addresses and every redirect, rejects local/private/metadata targets, checks file signatures, and verifies optional SHA-256 values.
- Use direct media-file URLs, not HTML preview pages. Do not put cookies, bearer tokens or account credentials in URLs.
- Required download failures fail the job. Optional assets can use required=false; however, any timeline cue that references a missing optional asset still fails validation.
- Music and SFX are placed by output-timeline seconds. Music can loop, fade and use explicit ducking_ranges. Timeline meme/B-roll cues refer to stable asset_id values.

See docs/ASSET_URLS.md for the complete manifest contract, supported formats and curl/ffprobe source checks.

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

Logs are written to both stdout/stderr and var/logs/worker.log. The local log rotates at 10 MB and keeps five backups. Follow PM2 output with pm2 logs render-worker. PM2 also stores its own logs in ~/.pm2/logs; configure PM2 log rotation separately if needed.

## PM2

From the repository root, install PM2 if it is not already available:

~~~bash
npm install -g pm2
~~~

If migrating an existing systemd deployment, stop and disable the old service first:

~~~bash
sudo systemctl disable --now render-worker
~~~

Start the worker and save the process list:

~~~bash
pm2 start ecosystem.config.js
pm2 status render-worker
pm2 save
pm2 logs render-worker
~~~

ecosystem.config.js resolves the repository path automatically and runs the Python CLI with .venv/bin/python. Activating the virtual environment is not required. The worker reads .env from the repository root. PM2 runs one instance, restarts it after failures with a five-second delay, and allows up to 60 seconds to stop after SIGINT before forcing termination. A stop or restart may interrupt an active render; the worker recovers interrupted jobs on its next polling cycle.

Do not run a second worker against the same mailbox or increase the PM2 instance count. This milestone uses a single-host lock, not a distributed lease.

To restore the saved processes after reboot:

~~~bash
pm2 startup
# Execute the sudo command printed by PM2, then:
pm2 save
~~~

On Ubuntu, this creates a pm2-<user> systemd service that starts PM2, which manages the worker. Keep the old render-worker systemd service disabled. If Node.js is managed with NVM, regenerate the PM2 startup configuration after changing Node.js versions.

Common commands (run as the same Ubuntu user, without sudo):

~~~bash
# Restart after changing .env or the ecosystem configuration.
pm2 restart ecosystem.config.js --update-env
pm2 logs render-worker --lines 100
pm2 stop render-worker
# Save after intentional process-list changes, including stopping/removing a worker.
pm2 save
~~~

The previous systemd unit remains in systemd/render-worker.service as an optional alternative for deployments that do not use PM2.

## Troubleshooting

- OAuth error: verify the OAuth consent screen, test-user list, Desktop client JSON, and local port-forward on 8765.
- Drive permission error: confirm the OAuth user owns or can edit the mailbox folder; for service accounts, confirm the folder is in a Shared Drive.
- No jobs found: check that the job folder is directly inside inbox and contains job.json.
- Waiting for job.json: finish uploading all assets and upload job.json last, or prepare the complete folder outside inbox and move it into inbox. A folder rejected before its upload finished must be moved from failed back to inbox after verifying its files are complete.
- Remote asset HTTP 403/404: the URL may be a preview page, expired signed URL, hotlink-protected media or require login. Replace it with a direct public media URL; do not add account cookies to the manifest.
- Remote asset rejected as private/local: use a public HTTPS CDN URL. The worker intentionally blocks localhost, private networks, metadata services and non-standard ports.
- Remote asset type mismatch: verify the file with curl, file and ffprobe. A successful HTTP response does not prove that the body is an audio/video/image file.
- Remote asset too large: reduce the source file or increase ASSET_DOWNLOAD_MAX_BYTES within the 1 GiB safety ceiling.
- Remotion not installed: run cd remotion && npm install.
- Font fallback: install Be Vietnam Pro or Noto Sans on Ubuntu and rerun the render.
- Failed job: inspect var/logs/worker.log, outputs/<job_id>/status-failed.json, and the input folder in failed.
- Interrupted job: restart the worker; active SQLite jobs are re-queued and downloaded again from processing.

## Output contract

A successful output must be H.264, yuv420p, requested dimensions and FPS, AAC when the source or remote audio tracks require audio, and decode fully with FFmpeg. Automated QA does not replace a human review of faces, safe zones, captions, crop, pacing, story accuracy and audio mix.
