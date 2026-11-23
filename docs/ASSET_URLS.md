# Remote media asset URLs

The Cloud editor can hand off media URLs instead of uploading every music/SFX/meme file itself. The local PC downloads the media during job processing.

## Job contract

Set input.asset_manifest in job.json:

~~~json
{
  "schema_version": "1.0",
  "job_id": "twin-vlog-2026-001",
  "input": {
    "source_video": "source/footage.mp4",
    "edl": "edl.json",
    "timeline": "timeline.json",
    "asset_manifest": "asset_manifest.json"
  }
}
~~~

Place asset_manifest.json beside job.json in the Drive job folder. The manifest uses stable asset IDs; timeline cues reference those IDs rather than repeating URLs.

## Asset manifest example

~~~json
{
  "schema_version": "1.0",
  "assets": [
    {
      "id": "music-bed",
      "kind": "music",
      "url": "https://cdn.example.net/direct/music-track.mp3",
      "start": 0,
      "end": 58,
      "volume": 0.14,
      "fade_in": 0.8,
      "fade_out": 1.5,
      "loop": true,
      "ducking_ranges": [
        {"start": 0.4, "end": 8.5, "volume": 0.28},
        {"start": 12.0, "end": 25.0, "volume": 0.28}
      ]
    },
    {
      "id": "sfx-hook-impact",
      "kind": "sfx",
      "url": "https://cdn.example.net/direct/impact.wav",
      "start": 0.35,
      "volume": 0.62,
      "fade_in": 0.01,
      "fade_out": 0.12
    },
    {
      "id": "meme-reaction",
      "kind": "meme",
      "url": "https://cdn.example.net/direct/reaction.gif"
    },
    {
      "id": "kitchen-broll",
      "kind": "broll",
      "url": "https://cdn.example.net/direct/kitchen-cutaway.mp4"
    }
  ]
}
~~~

The example host is illustrative. Replace it with a URL that returns the actual media bytes, not an HTML preview page.

## Timeline references

A meme cue overlays an image, animated GIF, or video. A B-roll cue overlays a video, full-screen by default.

~~~json
{
  "schema_version": "1.0",
  "layers": [
    {
      "id": "reaction-meme",
      "type": "meme",
      "asset_id": "meme-reaction",
      "start": 7.2,
      "end": 9.0,
      "x": 62,
      "y": 60,
      "width": 34,
      "height": 30,
      "fit": "contain"
    },
    {
      "id": "kitchen-cutaway",
      "type": "broll",
      "asset_id": "kitchen-broll",
      "start": 15.0,
      "end": 17.8,
      "fit": "cover"
    }
  ]
}
~~~

Audio asset times are in output-timeline seconds. start defaults to zero; end defaults to the end of the output. Music defaults to 0.16 volume and SFX to 0.72 if volume is omitted. Ducking ranges use output-timeline seconds and specify the multiplier applied while speech is present. Cloud should derive these intervals from the actual transcript/word timestamps.

## What counts as a downloadable URL?

Use a direct URL that returns media bytes, ideally with a media Content-Type and a stable file extension:

- Good: https://host.example/path/impact.wav
- Good: https://host.example/path/reaction.gif?download=1
- Good: a public CDN URL that redirects to the actual media file over HTTPS.
- Not supported: a YouTube/TikTok/Instagram/Spotify page URL, a web player page, a login page, or a DRM/protected streaming manifest.

A URL that opens a preview page in a browser is not necessarily a download URL. If a provider exposes a download button, inspect whether it links to a direct file URL. Do not bypass login, DRM, paywalls, or access controls.

## Quick source check

On the local PC, a candidate URL can be tested manually:

~~~bash
curl -L --fail --show-error --proto '=https' --proto-redir '=https' \
  -o /tmp/asset-check.bin 'https://host.example/path/file.wav'

file /tmp/asset-check.bin
ffprobe -v error -show_streams -show_format -of json /tmp/asset-check.bin
~~~

The worker uses Python requests with streaming downloads, manual redirect validation, and timeouts. It does not shell out to curl; the direct-file URL should work with ordinary HTTPS GET requests.

## Validation and limits

- HTTPS is mandatory by default. HTTP can be explicitly enabled with ASSET_DOWNLOAD_ALLOW_HTTP=true, but HTTPS is preferred.
- Localhost, private/reserved IP addresses, cloud metadata hosts, non-standard ports, and HTTPS-to-HTTP redirects are blocked.
- Every redirect target is validated before the next request.
- Global maximum defaults to 512 MiB. Per-kind defaults: music 100 MiB, SFX 25 MiB, meme 100 MiB, B-roll 512 MiB. The global cap can lower these limits.
- Supported audio: MP3, WAV, AAC, M4A, OGG/Opus, FLAC, and audio-only WebM.
- Supported memes: GIF, PNG, JPEG, WebP, MP4, WebM, MOV.
- Supported B-roll: MP4, WebM, MOV, M4V.
- sha256 is optional. When supplied, the downloaded file must match it.
- required: false allows a missing optional asset to be reported and skipped. If a timeline cue references a skipped asset, the job still fails validation.
- The worker writes VERIFIED or FAILED status, byte size, detected media type, source host, and SHA-256 into qa.json.

## Cloud editor handoff rules

1. Search for music/SFX/meme/B-roll that matches the beat.
2. Prefer direct downloadable CDN/media URLs over preview pages.
3. Do not include cookies, bearer tokens, account credentials, or signed URLs that expose private data in the manifest.
4. If a URL requires authentication or is app-only, mark it as unavailable for local download and do not pretend it was fetched.
5. Verify that the URL is intended for download and use. A successful HTTP download is not a license grant.
6. Add the URL and metadata to asset_manifest.json; add asset_id cues to timeline.json.
7. Upload the job folder to Drive and upload job.json last.
