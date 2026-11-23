# Remotion Local Render Worker

A local-first render worker for the Video Editor Engine. ChatGPT Cloud submits a job package to a Google Drive mailbox; an Ubuntu machine polls that mailbox, preprocesses footage with FFmpeg, downloads referenced public media assets, renders the composition with Remotion, runs media QA, and uploads the finished MP4 and reports to Drive.

The local machine makes outbound Google Drive and HTTPS media requests only. No inbound port, public webhook, Railway service, SSH tunnel, or exposed local API is required.

## Pipeline

1. ChatGPT Cloud analyzes footage and creates job.json, edl.json, timeline.json, and optional asset_manifest.json.
2. The asset manifest contains direct HTTPS media-file URLs for music, SFX, memes/GIFs, and B-roll. The Cloud editor does not need to download every media file itself.
3. The complete job folder is uploaded to Drive inbox. Upload job.json last so the worker does not claim an incomplete package.
4. The worker claims the folder, downloads Drive files, validates the job, then fetches each remote asset with Python requests.
5. Remote downloads are checked for public DNS/IP targets, HTTPS, redirect safety, size limits, file signatures, optional SHA-256, and media streams via FFprobe.
6. FFmpeg creates one normalized base.mp4, retaining source audio when present.
7. Remotion renders captions, comic bubbles, zoom/flash cues, image/GIF/video overlays, music, and SFX. The base video is played once with its original audio.
8. FFmpeg remuxes the result with faststart. QA checks H.264, yuv420p, dimensions, FPS, AAC when required, duration, and a full-file decode.
9. The worker uploads output.mp4, qa.json, and status.json, then moves the input job folder to completed. Failures are recorded and moved to failed.

## Supported first milestone

- Ubuntu 22.04/24.04, Python 3.10+, Node.js 20+, FFmpeg/FFprobe.
- Google Drive OAuth for personal My Drive; optional service account for Google Shared Drives.
- One render job at a time per worker process, protected by a host-level lock.
- Job input: source video or pre-edited base video, optional EDL and Remotion timeline.
- Remote assets: music, SFX, meme images/GIFs/videos, and B-roll videos.
- Audio: multiple music/SFX tracks with start/end, gain, fades, looping, and explicit ducking ranges.
- Visual overlays: caption, comic bubble, zoom, flash, meme and B-roll.
- 1080x1920, 30 FPS defaults; output settings are job-configurable.
- Local SQLite state, restart recovery, rotating logs, and PM2 process management.

The worker does not create a story, infer edits, transcribe dialogue, generate voice-over, or search for assets. Those creative decisions belong to the Cloud editor; the worker downloads and executes the supplied timeline and media manifest.

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

See docs/DRIVE_SETUP.md, docs/OPERATIONS.md, and docs/ASSET_URLS.md for setup and remote media URL requirements.

## Drive mailbox layout

The configured root folder is the mailbox. The worker creates inbox, processing, completed, failed, and outputs folders. Each inbox item is a folder containing job.json, all referenced local files, and optionally asset_manifest.json. Remote media files are fetched by the local worker from the URLs in that manifest. The worker never deletes source footage.

## Security

- Never commit .env, OAuth client secrets, OAuth tokens, service-account JSON, footage, or rendered MP4s.
- Never put cookies, bearer tokens, or private credentials in asset URLs or manifests.
- The downloader blocks localhost, private/reserved IP ranges, metadata endpoints, non-standard ports, HTTPS downgrade redirects, and non-public redirect targets.
- HTTPS is required by default. HTTP is opt-in through ASSET_DOWNLOAD_ALLOW_HTTP=true.
- Downloads have per-kind and global size limits. Optional SHA-256 hashes are supported.
- Only direct media-file URLs are supported. Preview pages, login-gated media, DRM, and protected streaming manifests are not bypassed.
- Use OAuth for personal My Drive. Use a service account only for a Shared Drive.
- Keep the worker on a machine and user account you control.
- Review every MP4 before publishing. Automated QA is technical validation, not human visual approval.
