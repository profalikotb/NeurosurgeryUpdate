from __future__ import annotations

import os
import string

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import audit, now_iso, session
from ..services import gdrive, indexer, jobs
from ..services.paths import normalize, os_path

router = APIRouter(prefix="/api", tags=["library"])


class FolderIn(BaseModel):
    path: str = Field(..., examples=[r"D:\Telegram books\Notebooklm books"])
    label: str | None = None


class FolderPatch(BaseModel):
    label: str | None = None
    enabled: bool | None = None


class ScanIn(BaseModel):
    folder_ids: list[int] | None = None
    force_reindex: bool = False


@router.get("/folders")
def list_folders():
    with session() as c:
        rows = c.execute("""
            SELECT f.*, COUNT(d.id) AS documents,
                   SUM(CASE WHEN d.status IN ('indexed','partial','ocr_needed') THEN 1 ELSE 0 END) AS indexed,
                   SUM(CASE WHEN d.status='error' THEN 1 ELSE 0 END) AS errors
            FROM folders f LEFT JOIN documents d ON d.folder_id = f.id GROUP BY f.id ORDER BY f.id""").fetchall()
    out = []
    for r in rows:
        drive = gdrive.is_drive(r["path"])
        out.append(dict(r) | {
            "source": "gdrive" if drive else "local",
            "web_link": f"https://drive.google.com/drive/folders/{gdrive.drive_id(r['path'])}" if drive else None,
            # Drive reachability is checked during scans (an API call per folder here would be slow).
            "reachable": gdrive.status()["configured"] if drive else os.path.isdir(os_path(r["path"])),
        })
    return out


@router.post("/folders", status_code=201)
def add_folder(body: FolderIn):
    if not get_settings().local_folders_enabled:
        raise HTTPException(403, "This server reads books from Google Drive only. Add a Google Drive folder instead.")
    path = normalize(body.path)
    if not os.path.isdir(os_path(path)):
        raise HTTPException(400, f"Folder not found or not accessible from the backend: {path}")
    with session() as c:
        if c.execute("SELECT 1 FROM folders WHERE path=?", (path,)).fetchone():
            raise HTTPException(409, "Folder already added")
        cur = c.execute("INSERT INTO folders(path, label, added_at) VALUES (?,?,?)",
                        (path, body.label or os.path.basename(path) or path, now_iso()))
        audit(c, "folder.added", path)
        return dict(c.execute("SELECT * FROM folders WHERE id=?", (cur.lastrowid,)).fetchone())


@router.patch("/folders/{folder_id}")
def patch_folder(folder_id: int, body: FolderPatch):
    with session() as c:
        if not c.execute("SELECT 1 FROM folders WHERE id=?", (folder_id,)).fetchone():
            raise HTTPException(404)
        if body.label is not None:
            c.execute("UPDATE folders SET label=? WHERE id=?", (body.label, folder_id))
        if body.enabled is not None:
            c.execute("UPDATE folders SET enabled=? WHERE id=?", (int(body.enabled), folder_id))
        return dict(c.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone())


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int):
    """Removes the folder and its documents from the index. Files on disk are never touched."""
    if jobs.active_job():
        raise HTTPException(409, "Wait for the running scan to finish")
    with session() as c:
        f = c.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone()
        if not f:
            raise HTTPException(404)
        doc_rows = c.execute("SELECT id, path, ext FROM documents WHERE folder_id=?", (folder_id,)).fetchall()
        ids = [r["id"] for r in doc_rows]
        for r in doc_rows:
            gdrive.evict(r)
        c.execute("UPDATE documents SET duplicate_of=NULL WHERE duplicate_of IN (SELECT id FROM documents WHERE folder_id=?)",
                  (folder_id,))
        c.execute("DELETE FROM documents WHERE folder_id=?", (folder_id,))
        c.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        audit(c, "folder.removed", f"{f['path']} ({len(ids)} documents de-indexed)")
    from ..services import semantic
    sem = semantic.get()
    if sem:
        for i in ids:
            try:
                sem.delete_document(i)
            except Exception:  # noqa: BLE001
                pass
    return {"removed_documents": len(ids)}


@router.post("/scan", status_code=202)
def start_scan(body: ScanIn):
    try:
        job_id = jobs.start("scan", lambda ctx: indexer.run_scan(ctx, body.folder_ids, body.force_reindex))
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"job_id": job_id}


@router.get("/jobs")
def list_jobs(limit: int = 20):
    with session() as c:
        rows = c.execute("SELECT id, kind, status, created_at, started_at, finished_at FROM jobs ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
        external = c.execute("SELECT id FROM jobs WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()
    # A running job may belong to another process (scheduled CLI scan); its progress is in the DB too.
    return {"active": jobs.active_job() or (external["id"] if external else None), "jobs": [dict(r) for r in rows]}


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404)
    return j


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    return {"cancelled": jobs.cancel(job_id)}


@router.get("/fs/browse")
def browse(path: str | None = None):
    """Directory picker for the UI (browsers cannot reveal local folder paths). Lists directories only."""
    if not get_settings().local_folders_enabled:
        raise HTTPException(403, "Browsing the server's disk is disabled on this server.")
    if not path:
        if os.name == "nt":
            roots = [f"{d}:\\" for d in string.ascii_uppercase if os.path.isdir(f"{d}:\\")]
        else:
            roots = ["/"] + [p for p in ("/data", "/books", "/mnt", os.path.expanduser("~")) if os.path.isdir(p)]
        return {"path": None, "parent": None, "dirs": [{"name": r, "path": r} for r in roots]}
    p = normalize(path)
    if not os.path.isdir(os_path(p)):
        raise HTTPException(404, "Not a directory")
    dirs = []
    try:
        with os.scandir(os_path(p)) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False) and not e.name.startswith((".", "$")):
                        dirs.append({"name": e.name, "path": normalize(os.path.join(p, e.name))})
                except OSError:
                    continue
    except PermissionError as e:
        raise HTTPException(403, "Permission denied") from e
    dirs.sort(key=lambda d: d["name"].lower())
    parent = os.path.dirname(p.rstrip("\\/")) if p not in ("/",) and not p.endswith(":\\") else None
    return {"path": p, "parent": parent or None, "dirs": dirs[:2000]}


class DriveFolderIn(BaseModel):
    link: str = Field(..., examples=["https://drive.google.com/drive/folders/1AbC..."])


@router.get("/gdrive/status")
def gdrive_status():
    s = get_settings()
    return gdrive.status() | {"local_folders_enabled": s.local_folders_enabled, "uploads_enabled": s.uploads_enabled}


@router.post("/gdrive/folders", status_code=201)
def add_drive_folder(body: DriveFolderIn):
    st = gdrive.status()
    if not st["configured"]:
        raise HTTPException(400, st["error"] or "Google Drive is not configured on this server (service-account key missing).")
    try:
        fid = gdrive.parse_folder_ref(body.link)
        meta = gdrive.folder_info(fid)
    except gdrive.DriveError as e:
        msg = str(e)
        if "not shared" in msg:
            msg = (f"The folder is not shared with {st['service_account_email']}. In Google Drive open the folder, "
                   "choose Share, add that address as Viewer, then try again.")
        raise HTTPException(400, msg) from e
    path = f"{gdrive.PREFIX}{fid}"
    with session() as c:
        if c.execute("SELECT 1 FROM folders WHERE path=?", (path,)).fetchone():
            raise HTTPException(409, "This Drive folder is already in the library")
        cur = c.execute("INSERT INTO folders(path, label, added_at) VALUES (?,?,?)",
                        (path, f"Google Drive: {meta.get('name') or fid}", now_iso()))
        audit(c, "folder.added", path)
        folder = dict(c.execute("SELECT * FROM folders WHERE id=?", (cur.lastrowid,)).fetchone())
    try:
        jobs.start("scan", lambda ctx: indexer.run_scan(ctx, [folder["id"]]))
    except RuntimeError:
        pass  # a scan is running; the watcher picks the new folder up afterwards
    return folder
