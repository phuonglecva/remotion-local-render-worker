from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload, MediaIoBaseDownload

from .models import decode_json_bytes


DRIVE_SCOPE = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[\\/\x00-\x1f]", "_", name).strip()
    if cleaned in ("", ".", ".."):
        raise ValueError("Unsafe Google Drive file name.")
    return cleaned


class DriveMailbox:
    def __init__(
        self,
        service_account_file: Path | None = None,
        oauth_client_file: Path | None = None,
        token_file: Path | None = None,
        allow_interactive: bool = False,
    ):
        if service_account_file:
            credentials = ServiceAccountCredentials.from_service_account_file(
                str(service_account_file), scopes=DRIVE_SCOPE
            )
            self.auth_method = "service_account"
        elif oauth_client_file:
            if not token_file:
                raise ValueError("GOOGLE_TOKEN_FILE must be configured for OAuth.")
            credentials = self._oauth_credentials(
                oauth_client_file, token_file, allow_interactive
            )
            self.auth_method = "oauth"
        else:
            raise ValueError("Configure OAuth client credentials or a Shared Drive service account.")
        self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    @staticmethod
    def _oauth_credentials(
        oauth_client_file: Path, token_file: Path, allow_interactive: bool
    ) -> UserCredentials:
        credentials = None
        refreshed = False
        if token_file.is_file():
            credentials = UserCredentials.from_authorized_user_file(
                str(token_file), scopes=DRIVE_SCOPE
            )

        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                refreshed = True
            except RefreshError:
                credentials = None

        if credentials and credentials.valid:
            if refreshed:
                token_file.write_text(credentials.to_json(), encoding="utf-8")
                os.chmod(token_file, 0o600)
            return credentials

        if not allow_interactive:
            raise RuntimeError(
                "No valid Google Drive OAuth token. Run 'render-worker auth-drive' once "
                "before starting the worker."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(oauth_client_file), scopes=DRIVE_SCOPE
        )
        print(
            "Authorize Google Drive in a browser. For a remote Ubuntu host, open an SSH tunnel "
            "with: ssh -L 8765:127.0.0.1:8765 USER@HOST"
        )
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=8765,
            open_browser=False,
            access_type="offline",
            prompt="consent",
        )
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")
        os.chmod(token_file, 0o600)
        return credentials

    def list_children(self, parent_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page_token = None
        while True:
            response = (
                self.service.files()
                .list(
                    q=f"'{parent_id}' in parents and trashed = false",
                    pageSize=1000,
                    pageToken=page_token,
                    orderBy="createdTime",
                    fields="nextPageToken,files(id,name,mimeType,parents,createdTime,size,webViewLink)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            results.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return results

    def find_child(
        self, parent_id: str, name: str, mime_type: str | None = None
    ) -> dict[str, Any] | None:
        for item in self.list_children(parent_id):
            if item.get("name") == name and (
                mime_type is None or item.get("mimeType") == mime_type
            ):
                return item
        return None

    def ensure_folder(self, parent_id: str, name: str) -> str:
        existing = self.find_child(parent_id, name, FOLDER_MIME)
        if existing:
            return existing["id"]
        created = (
            self.service.files()
            .create(
                body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
                fields="id,name",
                supportsAllDrives=True,
            )
            .execute()
        )
        return created["id"]

    def ensure_mailbox_folders(self, root_id: str) -> dict[str, str]:
        if self.auth_method == "service_account":
            root = (
                self.service.files()
                .get(fileId=root_id, fields="id,driveId", supportsAllDrives=True)
                .execute()
            )
            if not root.get("driveId"):
                raise ValueError(
                    "Service accounts cannot own files in personal My Drive. "
                    "Use OAuth for My Drive, or place this mailbox in a Google Shared Drive."
                )
        return {
            name: self.ensure_folder(root_id, name)
            for name in ("inbox", "processing", "completed", "failed", "outputs")
        }

    def list_inbox_folders(self, inbox_id: str) -> list[dict[str, Any]]:
        return [
            item for item in self.list_children(inbox_id) if item.get("mimeType") == FOLDER_MIME
        ]

    def read_json_child(self, parent_id: str, name: str) -> dict[str, Any]:
        item = self.find_child(parent_id, name)
        if not item:
            raise FileNotFoundError(f"Missing {name} in Drive job folder {parent_id}")
        content = self.download_bytes(item["id"])
        return json.loads(decode_json_bytes(content))

    def download_bytes(self, file_id: str) -> bytes:
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def download_file(self, file_id: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with destination.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    def download_folder_recursive(self, folder_id: str, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for item in self.list_children(folder_id):
            name = _safe_name(item["name"])
            target = destination / name
            if item.get("mimeType") == FOLDER_MIME:
                self.download_folder_recursive(item["id"], target)
            else:
                self.download_file(item["id"], target)

    def move_folder(self, folder_id: str, target_parent_id: str) -> None:
        metadata = (
            self.service.files()
            .get(fileId=folder_id, fields="id,parents", supportsAllDrives=True)
            .execute()
        )
        parents = metadata.get("parents", [])
        self.service.files().update(
            fileId=folder_id,
            addParents=target_parent_id,
            removeParents=",".join(parents) or None,
            fields="id,parents",
            supportsAllDrives=True,
        ).execute()

    def upload_file(
        self,
        local_path: Path,
        parent_id: str,
        name: str | None = None,
        mime_type: str = "video/mp4",
    ) -> dict[str, Any]:
        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
        return (
            self.service.files()
            .create(
                body={"name": name or local_path.name, "parents": [parent_id]},
                media_body=media,
                fields="id,name,size,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )

    def upload_json(self, value: dict[str, Any], parent_id: str, name: str) -> dict[str, Any]:
        payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        media = MediaInMemoryUpload(payload, mimetype="application/json", resumable=True)
        return (
            self.service.files()
            .create(
                body={"name": name, "parents": [parent_id]},
                media_body=media,
                fields="id,name,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
