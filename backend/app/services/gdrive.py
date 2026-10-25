"""Google Drive as a library source (read-only), for running the backend in the cloud without a PC.

Access model: a Google Cloud *service account* with the read-only Drive scope. You share one Drive folder
with the service account's e-mail address (Viewer); it can read that folder and everything inside it, and
nothing else in your Drive. No browser sign-in, no expiring refresh tokens.

Paths: a Drive folder is stored as ``gdrive://<folderId>``, a Drive file as ``gdrive://<fileId>``.
Change detection uses Drive's own MD5 checksum and modification time, so unchanged books are never
downloaded again. Books are downloaded once into ``<data_dir>/gdrive-cache`` for text extraction and page
images; the cache is refreshed when the file changes in Drive.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

PREFIX = "gdrive://"
API = "https://www.googleapis.com/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
GOOGLE_NATIVE = "application/vnd.google-apps."
DEFAULT_KEY_PATHS = ("/etc/secrets/google-service-account.json", "/etc/secrets/service-account.json")
FIELDS = "id,name,mimeType,size,md5Checksum,modifiedTime,trashed,shortcutDetails(targetId,targetMimeType)"


class DriveError(RuntimeError):
    pass


def is_drive(path: str | None) -> bool:
    return bool(path) and path.startswith(PREFIX)


def drive_id(path: str) -> str:
    return path[len(PREFIX):].split("/", 1)[0]


def parse_folder_ref(text: str) -> str:
    """Folder link or bare id -> id. Accepts .../folders/<id>, ...?id=<id>, or the id itself."""
    t = text.strip()
    for pat in (r"/folders/([A-Za-z0-9_-]{10,})", r"[?&]id=([A-Za-z0-9_-]{10,})", r"^([A-Za-z0-9_-]{10,})$"):
        m = re.search(pat, t)
        if m:
            return m.group(1)
    raise DriveError("Not a Google Drive folder link. Open the folder in Drive, choose Share > Copy link, and paste it.")


# ------------------------------------------------------------------------------------------ credentials
_key_cache: dict[str, Any] | None = None


def _load_key() -> dict[str, Any] | None:
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    s = get_settings()
    raw = s.gdrive_service_account_json
    if raw:
        raw = raw.strip()
        if not raw.startswith("{"):
            try:
                raw = base64.b64decode(raw).decode("utf-8")
            except Exception as e:  # noqa: BLE001
                raise DriveError("ACADEMY_GDRIVE_SERVICE_ACCOUNT_JSON is neither JSON nor base64 JSON") from e
        _key_cache = json.loads(raw)
        return _key_cache
    for p in ([s.gdrive_service_account_file] if s.gdrive_service_account_file else []) + list(DEFAULT_KEY_PATHS):
        if p and os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                _key_cache = json.load(fh)
            return _key_cache
    return None


def status() -> dict[str, Any]:
    try:
        key = _load_key()
    except Exception as e:  # noqa: BLE001
        return {"configured": False, "error": str(e), "service_account_email": None}
    if not key:
        return {"configured": False, "error": None, "service_account_email": None}
    return {"configured": True, "error": None, "service_account_email": key.get("client_email")}


class _Token:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: str | None = None
        self._expiry = 0.0

    def get(self) -> str:
        with self._lock:
            if self._value and time.time() < self._expiry - 120:
                return self._value
            key = _load_key()
            if not key:
                raise DriveError("Google Drive is not configured: the service-account key is missing (see docs/CLOUD_DRIVE.md).")
            try:
                from google.auth.transport.requests import Request
                from google.oauth2 import service_account
            except ImportError as e:  # pragma: no cover
                raise DriveError("google-auth is not installed (pip install -r requirements.txt)") from e
            creds = service_account.Credentials.from_service_account_info(key, scopes=[SCOPE])
            from google.auth import exceptions as gexc
            try:
                creds.refresh(Request())
            except gexc.TransportError as e:
                raise DriveError(f"Google sign-in server unreachable (no internet?): {e}") from e
            except gexc.RefreshError as e:
                raise DriveError(f"Google rejected the service-account key (deleted or disabled?): {e}") from e
            self._value = creds.token
            self._expiry = creds.expiry.timestamp() if creds.expiry else time.time() + 3000
            return self._value


_token = _Token()


def token() -> str:
    return _token.get()


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=True)


def _get(c: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(4):
        try:
            r = c.get(url, params=params, headers={"Authorization": f"Bearer {token()}"})
        except httpx.TransportError as e:
            if attempt == 3:
                raise DriveError(f"Google Drive unreachable: {e}") from e
            time.sleep(1 + attempt)
            continue
        if r.status_code in (429, 500, 502, 503) or (r.status_code == 403 and "rateLimit" in r.text):
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise DriveError("not found or not shared with the service account")
        if r.status_code == 401:
            _token._value = None
            continue
        if r.status_code >= 400:
            raise DriveError(f"Google Drive error {r.status_code}: {r.text[:200]}")
        return r.json()
    raise DriveError("Google Drive is rate-limiting requests; try again in a minute")


# ------------------------------------------------------------------------------------------ listing
@dataclass
class DriveFile:
    id: str
    name: str
    size: int
    mtime: float
    md5: str | None
    mime: str
    path_hint: str  # "Sub folder/Book.pdf", for logs and display


def _ts(s: str | None) -> float:
    if not s:
        return 0.0
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def folder_info(folder_id: str) -> dict[str, Any]:
    with _client() as c:
        meta = _get(c, f"{API}/files/{folder_id}", {"fields": "id,name,mimeType", "supportsAllDrives": "true"})
    if meta.get("mimeType") != FOLDER_MIME:
        raise DriveError("This link points to a file, not a folder. Share the folder that contains the books.")
    return meta


def list_tree(folder_id: str, exts: set[str], log_fn=None) -> list[DriveFile]:
    """All supported files below a folder (recursive). Shortcuts are followed when their target is shared."""
    out: list[DriveFile] = []
    seen_folders: set[str] = set()
    with _client() as c:
        stack = [(folder_id, "")]
        while stack:
            fid, prefix = stack.pop()
            if fid in seen_folders:
                continue
            seen_folders.add(fid)
            page = None
            while True:
                params = {"q": f"'{fid}' in parents and trashed=false", "fields": f"nextPageToken,files({FIELDS})",
                          "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
                if page:
                    params["pageToken"] = page
                data = _get(c, f"{API}/files", params)
                for f in data.get("files", []):
                    name = f.get("name", "")
                    mime = f.get("mimeType", "")
                    if mime == FOLDER_MIME:
                        stack.append((f["id"], f"{prefix}{name}/"))
                        continue
                    if mime == SHORTCUT_MIME:
                        tgt = (f.get("shortcutDetails") or {}).get("targetId")
                        try:
                            f = _get(c, f"{API}/files/{tgt}", {"fields": FIELDS, "supportsAllDrives": "true"})
                        except DriveError:
                            if log_fn:
                                log_fn(f"Shortcut '{prefix}{name}' points to a file that is not shared with the "
                                       f"service account. Move the file itself into the shared folder.")
                            continue
                        mime = f.get("mimeType", "")
                        if mime == FOLDER_MIME:
                            stack.append((f["id"], f"{prefix}{name}/"))
                            continue
                    if mime.startswith(GOOGLE_NATIVE):
                        continue  # Google Docs/Slides have no file to download; export them to PDF in Drive
                    ext = Path(f.get("name", name)).suffix.lower()
                    if ext not in exts:
                        continue
                    out.append(DriveFile(id=f["id"], name=f.get("name", name), size=int(f.get("size") or 0),
                                         mtime=_ts(f.get("modifiedTime")), md5=f.get("md5Checksum"), mime=mime,
                                         path_hint=f"{prefix}{f.get('name', name)}"))
                page = data.get("nextPageToken")
                if not page:
                    break
    return out


# ------------------------------------------------------------------------------------------ cache
def cache_dir() -> Path:
    p = get_settings().data_dir / "gdrive-cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_path(file_id: str, ext: str) -> Path:
    return cache_dir() / f"{file_id}{ext.lower()}"


_dl_locks: dict[str, threading.Lock] = {}
_dl_guard = threading.Lock()


def download(file_id: str, ext: str, expected_size: int | None = None, cancelled=None) -> Path:
    dest = cache_path(file_id, ext)
    with _dl_guard:
        lock = _dl_locks.setdefault(file_id, threading.Lock())
    with lock:
        if dest.exists() and (not expected_size or dest.stat().st_size == expected_size):
            return dest
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with _client() as c, c.stream("GET", f"{API}/files/{file_id}",
                                          params={"alt": "media", "supportsAllDrives": "true", "acknowledgeAbuse": "true"},
                                          headers={"Authorization": f"Bearer {token()}"}) as r:
                if r.status_code == 404:
                    raise DriveError("file not found or no longer shared")
                if r.status_code >= 400:
                    raise DriveError(f"download failed: HTTP {r.status_code}")
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_bytes(1024 * 1024):
                        if cancelled and cancelled():
                            raise InterruptedError("cancelled")
                        fh.write(chunk)
            tmp.replace(dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return dest


def local_copy(doc: Any, cancelled=None) -> str:
    """Local file path for a document row (downloads Drive files into the cache on first use)."""
    path = doc["path"]
    if not is_drive(path):
        return path
    return str(download(drive_id(path), doc["ext"], doc["size"], cancelled))


def evict(doc: Any) -> None:
    if is_drive(doc["path"]):
        cache_path(drive_id(doc["path"]), doc["ext"]).unlink(missing_ok=True)


def web_link(path: str) -> str | None:
    return f"https://drive.google.com/file/d/{drive_id(path)}/view" if is_drive(path) else None
