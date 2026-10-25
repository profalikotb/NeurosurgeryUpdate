"""Upload books from the browser (e.g. the iPhone file picker, which can read Google Drive / iCloud files).

PUT /api/library/upload?filename=<name> with the raw file as the body. The body is streamed to disk, so even
large textbooks need no memory. Uploaded books live in <data_dir>/<uploads_folder_name>, which is registered as
a library folder automatically and indexed immediately.
"""
from __future__ import annotations

import os
import re
import secrets
import time
import unicodedata
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from ..config import get_settings
from ..db import audit, now_iso, session
from ..services import indexer, jobs, semantic
from ..services.paths import is_within, normalize

router = APIRouter(prefix="/api/library", tags=["uploads"])
MAGIC = {".pdf": b"%PDF-", ".epub": b"PK", ".docx": b"PK"}


def uploads_dir() -> Path:
    s = get_settings()
    p = s.data_dir / s.uploads_folder_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_filename(name: str) -> str:
    name = unicodedata.normalize("NFC", os.path.basename(name.replace("\\", "/"))).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    stem, ext = os.path.splitext(name)
    return (stem[:150].rstrip(" .") or "book") + ext.lower()


def ensure_uploads_folder() -> int:
    path = normalize(uploads_dir())
    with session() as c:
        row = c.execute("SELECT id FROM folders WHERE path=?", (path,)).fetchone()
        if row:
            return row["id"]
        return c.execute("INSERT INTO folders(path, label, added_at) VALUES (?,?,?)",
                         (path, get_settings().uploads_folder_name, now_iso())).lastrowid


RE_UPLOAD_ID = re.compile(r"^[a-f0-9]{16,64}$")


@router.put("/upload", status_code=201)
async def upload(request: Request, filename: str = Query(..., min_length=1, max_length=300),
                 upload_id: str | None = Query(None), offset: int = Query(0, ge=0), final: bool = True):
    """Single request (whole file as body), or chunked: the browser sends consecutive parts with the same
    upload_id and the byte offset of each part, and final=true on the last one. Chunking keeps memory flat
    and lets a phone resume after a dropped connection (409 returns the size received so far)."""
    s = get_settings()
    if not s.uploads_enabled:
        raise HTTPException(403, "Uploading is disabled on this server")
    name = _safe_filename(filename)
    ext = Path(name).suffix.lower()
    if ext not in {e.lower() for e in s.supported_extensions}:
        raise HTTPException(415, f"Unsupported file type '{ext or '?'}'. Supported: "
                                 + ", ".join(sorted(s.supported_extensions)))
    if upload_id is not None and not RE_UPLOAD_ID.match(upload_id):
        raise HTTPException(400, "bad upload_id")
    folder = uploads_dir()
    tmp = folder / f".upload-{upload_id}.part" if upload_id else folder / f".{secrets.token_hex(8)}.part"
    limit = s.max_file_mb * 1024 * 1024
    have = tmp.stat().st_size if (upload_id and tmp.exists()) else 0
    if upload_id and offset != have:
        raise HTTPException(409, {"message": "offset mismatch", "received": have})
    size = have
    try:
        with open(tmp, "ab" if upload_id else "wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File larger than {s.max_file_mb} MB")
                fh.write(chunk)
    except BaseException:
        if not upload_id or size > limit:
            tmp.unlink(missing_ok=True)
        raise
    if not final:
        return {"received": size}
    try:
        if size == 0:
            raise HTTPException(400, "The file is empty (the upload may have been interrupted)")
        with open(tmp, "rb") as fh:
            head = fh.read(8)
        magic = MAGIC.get(ext)
        if magic and not head.startswith(magic):
            raise HTTPException(415, f"This does not look like a real {ext} file. If it came from Google Drive, "
                                     "download it to the phone first, then upload.")
        dest = folder / name
        n = 2
        while dest.exists():
            dest = folder / f"{Path(name).stem} ({n}){ext}"
            n += 1
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    # Mark the file as "settled" so the download-in-progress guard does not delay indexing.
    old = time.time() - max(120, s.min_file_age_seconds + 60)
    os.utime(dest, (old, old))
    folder_id = ensure_uploads_folder()
    with session() as c:
        audit(c, "upload", f"{dest.name} ({size} bytes)")
    started = None
    try:
        started = jobs.start("upload-scan", lambda ctx: indexer.run_scan(ctx, [folder_id]))
    except RuntimeError:
        pass  # another scan is running; the automatic watcher indexes the new book right after it
    return {"filename": dest.name, "size": size, "job_id": started}


@router.delete("/upload/{doc_id}")
def delete_uploaded(doc_id: int):
    """Delete a book that was uploaded through the browser (file and index). Other library files are never deleted."""
    with session() as c:
        d = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if d is None:
            raise HTTPException(404)
        if not is_within(d["path"], normalize(uploads_dir())):
            raise HTTPException(403, "Only books uploaded through the app can be deleted here")
        dups = [r["id"] for r in c.execute("SELECT id FROM documents WHERE duplicate_of=?", (doc_id,))]
        c.execute("UPDATE documents SET duplicate_of=NULL, status='pending' WHERE duplicate_of=?", (doc_id,))
        c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        audit(c, "upload.deleted", d["path"])
    Path(d["path"]).unlink(missing_ok=True)
    sem = semantic.get()
    if sem:
        try:
            sem.delete_document(doc_id)
        except Exception:  # noqa: BLE001
            pass
    if dups:
        try:
            jobs.start("reindex", lambda ctx: indexer.reindex_documents(ctx, dups))
        except RuntimeError:
            pass
    return {"deleted": True}
