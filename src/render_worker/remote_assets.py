from __future__ import annotations

import hashlib
import ipaddress
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from .models import AssetManifest, RemoteAssetSpec


logger = logging.getLogger("render_worker.assets")

MAX_BYTES_BY_KIND = {
    "music": 100 * 1024 * 1024,
    "sfx": 25 * 1024 * 1024,
    "meme": 100 * 1024 * 1024,
    "broll": 512 * 1024 * 1024,
}

MIME_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/aac": ".aac",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "image/gif": ".gif",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

ALLOWED_EXTENSIONS = {
    "music": {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac", ".opus", ".webm"},
    "sfx": {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac", ".opus", ".webm"},
    "meme": {".gif", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov"},
    "broll": {".mp4", ".webm", ".mov", ".m4v"},
}


class AssetDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadedAsset:
    asset_id: str
    kind: str
    local_path: Path
    media_type: str
    mime_type: str
    size_bytes: int
    sha256: str
    source_host: str
    resolved_url: str


def _public_addresses(hostname: str) -> list[str]:
    try:
        address = ipaddress.ip_address(hostname)
        addresses = [str(address)]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise AssetDownloadError(f"Could not resolve asset host '{hostname}'.") from exc
        addresses = list({record[4][0] for record in records})

    if not addresses:
        raise AssetDownloadError(f"Asset host '{hostname}' has no resolved addresses.")
    for value in addresses:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        if not address.is_global:
            raise AssetDownloadError(
                f"Blocked non-public asset host address for '{hostname}'."
            )
    return addresses


def validate_download_url(url: str, allow_http: bool = False) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme != "https" and not (allow_http and scheme == "http"):
        raise AssetDownloadError("Asset downloads require HTTPS (HTTP is disabled by default).")
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise AssetDownloadError("Asset URL must have a public host and no credentials/fragments.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise AssetDownloadError("Asset URL has an invalid port.") from exc
    expected_port = 443 if scheme == "https" else 80
    if port not in (None, expected_port):
        raise AssetDownloadError("Asset URL uses a non-standard port, which is blocked.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise AssetDownloadError(f"Blocked local or metadata hostname '{host}'.")
    _public_addresses(host)
    return host


def _sniff(prefix: bytes, content_type: str) -> tuple[str, str | None]:
    lowered = content_type.lower()
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return "gif", ".gif"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", ".png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image", ".jpg"
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
        return "image", ".webp"
    if prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE":
        return "audio", ".wav"
    if prefix.startswith(b"fLaC"):
        return "audio", ".flac"
    if prefix.startswith(b"OggS"):
        return "audio", ".ogg"
    if prefix.startswith(b"ID3"):
        return "audio", ".mp3"
    if len(prefix) > 1 and prefix[0] == 0xFF and (prefix[1] & 0xE0) == 0xE0:
        return "audio", ".mp3"
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        return "container", MIME_EXTENSIONS.get(lowered)
    if prefix.startswith(b"\x1aE\xdf\xa3"):
        return "container", MIME_EXTENSIONS.get(lowered) or ".webm"
    if lowered.startswith("audio/"):
        return "audio", MIME_EXTENSIONS.get(lowered)
    if lowered.startswith("video/"):
        return "video", MIME_EXTENSIONS.get(lowered)
    return "unknown", None


def _safe_extension(media_type: str, sniffed_extension: str | None, content_type: str) -> str:
    if sniffed_extension:
        return sniffed_extension
    extension = MIME_EXTENSIONS.get(content_type.lower())
    if extension:
        return extension
    if media_type == "container":
        return ".media"
    raise AssetDownloadError(
        f"Could not identify a supported media file (Content-Type: {content_type or 'unknown'})."
    )


class RemoteAssetDownloader:
    def __init__(
        self,
        timeout_seconds: int = 30,
        max_bytes: int = 512 * 1024 * 1024,
        allow_http: bool = False,
        max_redirects: int = 5,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.allow_http = allow_http
        self.max_redirects = max_redirects

    def download_all(
        self, manifest: AssetManifest, destination: Path
    ) -> tuple[dict[str, DownloadedAsset], list[dict[str, object]]]:
        destination.mkdir(parents=True, exist_ok=True)
        downloaded: dict[str, DownloadedAsset] = {}
        report: list[dict[str, object]] = []
        for spec in manifest.assets:
            try:
                asset = self.download(spec, destination)
                downloaded[spec.id] = asset
                report.append({
                    "id": spec.id,
                    "kind": spec.kind,
                    "status": "VERIFIED",
                    "source_host": asset.source_host,
                    "resolved_url": asset.resolved_url,
                    "local_file": asset.local_path.relative_to(destination.parent).as_posix(),
                    "media_type": asset.media_type,
                    "mime_type": asset.mime_type,
                    "size_bytes": asset.size_bytes,
                    "sha256": asset.sha256,
                })
                logger.info(
                    "Downloaded asset %s (%s, %s bytes, sha256=%s)",
                    spec.id, asset.media_type, asset.size_bytes, asset.sha256[:12],
                )
            except Exception as exc:
                report.append({
                    "id": spec.id,
                    "kind": spec.kind,
                    "status": "FAILED",
                    "error": str(exc)[:1500],
                })
                if spec.required:
                    raise AssetDownloadError(
                        f"Required remote asset '{spec.id}' could not be downloaded: {exc}"
                    ) from exc
                logger.warning("Optional asset %s was skipped: %s", spec.id, exc)
        return downloaded, report

    def download(self, spec: RemoteAssetSpec, destination: Path) -> DownloadedAsset:
        max_bytes = min(
            spec.max_bytes or MAX_BYTES_BY_KIND[spec.kind],
            self.max_bytes,
            MAX_BYTES_BY_KIND[spec.kind],
        )
        current_url = spec.url
        source_host = validate_download_url(current_url, self.allow_http)
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": "RemotionLocalRenderWorker/1.0"})
        response = None
        try:
            for redirect_count in range(self.max_redirects + 1):
                host = validate_download_url(current_url, self.allow_http)
                if source_host != host and urlsplit(current_url).scheme == "http":
                    raise AssetDownloadError("Cross-host HTTP redirects are blocked.")
                response = session.get(
                    current_url,
                    stream=True,
                    allow_redirects=False,
                    timeout=(10, self.timeout_seconds),
                )
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    response.close()
                    if not location or redirect_count >= self.max_redirects:
                        raise AssetDownloadError("Asset URL exceeded the redirect limit.")
                    next_url = urljoin(current_url, location)
                    if urlsplit(current_url).scheme == "https" and urlsplit(next_url).scheme != "https":
                        raise AssetDownloadError("HTTPS-to-HTTP redirects are blocked.")
                    current_url = next_url
                    continue
                if response.status_code != 200:
                    raise AssetDownloadError(f"Asset server returned HTTP {response.status_code}.")
                break
            else:
                raise AssetDownloadError("Asset URL exceeded the redirect limit.")

            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            declared_length = response.headers.get("Content-Length")
            if declared_length:
                try:
                    if int(declared_length) > max_bytes:
                        raise AssetDownloadError(
                            f"Asset exceeds the {max_bytes}-byte download limit."
                        )
                except ValueError:
                    pass

            partial_path = destination / f".{spec.id}.part"
            digest = hashlib.sha256()
            size = 0
            prefix = bytearray()
            try:
                with partial_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > max_bytes:
                            raise AssetDownloadError(
                                f"Asset exceeded the {max_bytes}-byte download limit."
                            )
                        if len(prefix) < 64:
                            prefix.extend(chunk[: 64 - len(prefix)])
                        digest.update(chunk)
                        handle.write(chunk)
                media_type, sniffed_extension = _sniff(bytes(prefix), content_type)
                if media_type == "unknown":
                    raise AssetDownloadError(
                        f"Downloaded URL did not return a recognizable media file "
                        f"(Content-Type: {content_type or 'unknown'})."
                    )
                if spec.kind in ("music", "sfx") and media_type not in ("audio", "container"):
                    raise AssetDownloadError(f"{spec.kind} URL returned {media_type}, not audio.")
                if spec.kind == "broll" and media_type not in ("video", "container"):
                    raise AssetDownloadError(f"B-roll URL returned {media_type}, not video.")
                if spec.kind == "meme" and media_type not in ("image", "gif", "video", "container"):
                    raise AssetDownloadError(f"Meme URL returned unsupported media type {media_type}.")

                extension = _safe_extension(media_type, sniffed_extension, content_type)
                if extension == ".media":
                    url_extension = Path(urlsplit(current_url).path).suffix.lower()
                    extension = url_extension if url_extension in ALLOWED_EXTENSIONS[spec.kind] else extension
                if extension not in ALLOWED_EXTENSIONS[spec.kind]:
                    raise AssetDownloadError(
                        f"File extension {extension} is not supported for asset kind {spec.kind}."
                    )
                actual_sha256 = digest.hexdigest()
                if spec.sha256 and actual_sha256.lower() != spec.sha256.lower():
                    raise AssetDownloadError("Downloaded asset SHA-256 does not match the manifest.")
                final_path = destination / f"{spec.id}{extension}"
                partial_path.replace(final_path)
            except Exception:
                partial_path.unlink(missing_ok=True)
                raise

            final_host = urlsplit(current_url).hostname or source_host
            return DownloadedAsset(
                asset_id=spec.id,
                kind=spec.kind,
                local_path=final_path,
                media_type=media_type,
                mime_type=content_type or "application/octet-stream",
                size_bytes=size,
                sha256=actual_sha256,
                source_host=final_host,
                resolved_url=f"{urlsplit(current_url).scheme}://{final_host}{urlsplit(current_url).path}",
            )
        except requests.RequestException as exc:
            raise AssetDownloadError(f"HTTP download failed: {exc.__class__.__name__}.") from exc
        finally:
            if response is not None:
                response.close()
            session.close()
