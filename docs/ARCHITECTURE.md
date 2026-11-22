# Architecture

ChatGPT Cloud and the local Ubuntu worker communicate through a Google Drive mailbox. The worker initiates outbound HTTPS requests to Google Drive; no inbound listener is opened on the home network. Drive is the transport boundary, not the render engine.

## Job lifecycle

~~~text
Drive inbox -> claim folder -> SQLite QUEUED
  -> DOWNLOADING -> VALIDATING -> PREPROCESSING -> base.mp4
  -> RENDERING -> Remotion output -> FFmpeg faststart mux
  -> QA -> UPLOADING -> SUCCEEDED
  Any active state may transition to FAILED.
~~~

SQLite is authoritative for local job state. Drive folders show the operator-facing state. The worker processes jobs sequentially; Remotion concurrency controls frame rendering within a job, not concurrent jobs.

## Render responsibilities

- FFmpeg: source probing, trims, speed changes, aspect-ratio normalization, audio preservation, base.mp4 generation, final faststart remux, and full-file decode.
- Remotion: deterministic captions, comic bubbles, zooms, and flash overlays.
- SQLite: durable state, duplicate job detection, and recovery after process restart.
- Google Drive: job transport and output delivery.

The Remotion composition uses @remotion/media Video for base.mp4 and does not add a second Audio layer. This prevents duplicate source audio.

## Recovery and idempotency

A job folder is moved from inbox to processing before download. The job ID is unique in SQLite. On restart, non-terminal jobs are reset to QUEUED and reprocessed from their Drive processing folder. Duplicate job IDs are moved to failed rather than silently overwriting a prior output.

A job is successful only after the final MP4 passes ffprobe checks and a full FFmpeg decode, and the output plus QA/status JSON have uploaded successfully.

## Deliberate non-goals

No public webhook, port forwarding, Redis, Railway deployment, multi-host distributed lock, AI story planning, transcription, voice cloning, asset discovery, or TikTok publishing. Run one worker instance against one mailbox.
