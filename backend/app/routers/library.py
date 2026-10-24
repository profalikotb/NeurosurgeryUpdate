from __future__ import annotations

import os
import string

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import audit, now_iso, session
from ..services import indexer, jobs
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
    return [dict(r) | {"reachable": os.path.isdir(os_path(r["path"]))} for r in rows]


@router.post("/folders", status_code=201)
def add_folder(body: FolderIn):
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
        ids = [r["id"] for r in c.execute("SELECT id FROM documents WHERE folder_id=?", (folder_id,))]
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
