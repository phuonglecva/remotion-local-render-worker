# Remotion Local Render Worker

A local-first render worker for the Video Editor Engine. ChatGPT Cloud submits a job package to a Google Drive mailbox; an Ubuntu machine polls that mailbox, preprocesses footage with FFmpeg, renders overlays with Remotion, runs media QA, and uploads the finished MP4 and reports to Drive.

The local machine makes outbound Google Drive API requests only. No inbound port, public webhook, Railway service, SSH tunnel, or exposed local API is required.

## Pipeline

1. ChatGPT Cloud or an operator places a job folder in the Drive mailbox inbox.
2. The worker claims the folder by moving it to processing and records the job in SQLite.
3. It downloads the job and validates the manifest, paths, video streams, and optional EDL/timeline.
4. FFmpeg creates one normalized base.mp4, retaining source audio when present.
5. Remotion renders the base video plus timeline overlays. The base video is played exactly once with its original audio.
6. FFmpeg remuxes the result with faststart. QA checks H.264, yuv420p, dimensions, FPS, AAC when required, duration, and a full-file decode.
7. The worker uploads output.mp4, qa.json, and status.json, then moves the input job folder to completed. Failures are recorded and moved to failed.

## Supported first milestone

- Ubuntu 22.04/24.04, Python 3.10+, Node.js 20+, FFmpeg/FFprobe.
- Google Drive OAuth for personal My Drive; optional service account for Google Shared Drives.
- One render job at a time per worker process, protected by a host-level lock.
- Job input: source_video or pre-edited base_video.
- Optional EDL cuts and 0.5x–2.0x speed changes.
- Remotion caption, comic bubble, zoom, and flash cues.
- 1080x1920, 30 FPS defaults; output settings are job-configurable.
- Local SQLite state, restart recovery, rotating logs, and PM2 process management.

The worker does not create a story, infer edits, transcribe dialogue, generate voice-over, search B-roll, or auto-publish to TikTok. Those decisions belong to the Cloud editor; this repository executes a validated render job.

## Quick start on Ubuntu

~~~bash
git clone https://github.com/phuonglecva/remotion-local-render-worker.git
cd remotion-local-render-worker
cp .env.example .env
chmod +x scripts/bootstrap_ubuntu.sh
./scripts/bootstrap_ubuntu.sh
~~~

Create a Google OAuth Desktop client in Google Cloud Console, download its JSON file to the Ubuntu machine, then set GOOGLE_OAUTH_CLIENT_FILE and DRIVE_MAILBOX_ROOT_ID in .env. Run:

~~~bash
source .venv/bin/activate
render-worker auth-drive
render-worker setup-drive
render-worker doctor
render-worker run --once
~~~

For a headless remote Ubuntu host, use the SSH port-forward command printed by auth-drive while authorizing in your desktop browser. The OAuth token is stored in var/google-token.json with owner-only permissions and is excluded from Git.

Run continuously with PM2, using the same Ubuntu user that completed Drive authorization:

~~~bash
npm install -g pm2  # Only if PM2 is not already installed.
pm2 start ecosystem.config.js
pm2 save
pm2 logs render-worker
~~~

If migrating from systemd, run `sudo systemctl disable --now render-worker` before starting PM2. To start PM2 after reboot, run `pm2 startup` and execute the sudo command it prints.

See docs/DRIVE_SETUP.md and docs/OPERATIONS.md for setup, migration, and process management details.

## Drive mailbox layout

The configured root folder is the mailbox. The worker creates inbox, processing, completed, failed, and outputs folders. Each inbox item must be a folder containing job.json and all referenced assets. See examples/jobs/example for the contract. The worker never deletes source footage.

## Security

- Never commit .env, OAuth client secrets, OAuth tokens, service-account JSON, footage, or rendered MP4s.
- Use OAuth for personal My Drive. Use a service account only for a Shared Drive.
- Keep the worker on a machine and user account you control.
- Review every MP4 before publishing. Automated QA is technical validation, not human visual approval.
