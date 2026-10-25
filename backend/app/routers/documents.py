from __future__ import annotations

import mimetypes
import os
import re

import pymupdf
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import get_settings
from ..db import audit, session
from ..services import citations, gdrive, indexer, jobs
from ..services.paths import os_path

router = APIRouter(prefix="/api/documents", tags=["documents"])
RENDERABLE = {".pdf", ".epub", ".mobi", ".fb2"}
SORTS = {"title": "COALESCE(title, filename) COLLATE NOCASE", "added": "added_at DESC", "quality": "quality_score",
         "pages": "page_count DESC", "status": "status"}


class MetaPatch(BaseModel):
    title: str | None = None
    authors: str | None = None
    edition: str | None = None
    year: int | None = None
    publisher: str | None = None
    isbn: str | None = None
    metadata_verified: bool | None = None


def _doc_or_404(c, doc_id: int):
    d = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not d:
        raise HTTPException(404, "document not found")
    return d


@router.get("")
def list_documents(status: str | None = None, folder_id: int | None = None, q: str | None = None,
                   sort: str = "title", limit: int = Query(200, le=2000), offset: int = 0):
    where, params = ["1=1"], []
    if status:
        where.append(f"status IN ({','.join('?' * len(status.split(',')))})")
        params += status.split(",")
    if folder_id:
        where.append("folder_id=?")
        params.append(folder_id)
    if q:
        where.append("(title LIKE ? OR filename LIKE ? OR authors LIKE ?)")
        params += [f"%{q}%"] * 3
    w = " AND ".join(where)
    with session() as c:
        total = c.execute(f"SELECT COUNT(*) FROM documents WHERE {w}", params).fetchone()[0]
        rows = c.execute(f"SELECT * FROM documents WHERE {w} ORDER BY {SORTS.get(sort, SORTS['title'])} LIMIT ? OFFSET ?",
                         (*params, limit, offset)).fetchall()
    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/{doc_id}")
def get_document(doc_id: int):
    with session() as c:
        d = dict(_doc_or_404(c, doc_id))
        d["toc"] = [dict(r) for r in c.execute("SELECT level, title, start_page, end_page FROM toc WHERE document_id=? "
                                               "ORDER BY seq", (doc_id,))]
        d["duplicates"] = [dict(r) for r in c.execute("SELECT id, path FROM documents WHERE duplicate_of=?", (doc_id,))]
        from ..services.paths import is_within as _within
        from .uploads import uploads_dir
        d["source"] = "gdrive" if gdrive.is_drive(d["path"]) else "local"
        d["uploaded"] = (not gdrive.is_drive(d["path"])) and _within(d["path"], str(uploads_dir()))
        d["web_link"] = gdrive.web_link(d["path"])
        d["exists_on_disk"] = True if gdrive.is_drive(d["path"]) else os.path.isfile(os_path(d["path"]))
    return d


@router.patch("/{doc_id}")
def patch_metadata(doc_id: int, body: MetaPatch):
    """User-entered values get provenance 'user' and are never overwritten by re-indexing."""
    data = body.model_dump(exclude_unset=True)
    with session() as c:
        _doc_or_404(c, doc_id)
        for k, v in data.items():
            if k == "metadata_verified":
                c.execute("UPDATE documents SET metadata_verified=? WHERE id=?", (int(bool(v)), doc_id))
            else:
                v = v.strip() if isinstance(v, str) else v
                c.execute(f"UPDATE documents SET {k}=?, {k}_src=? WHERE id=?", (v or None, "user" if v else None, doc_id))
        audit(c, "document.metadata", f"{doc_id}: {sorted(data)}")
        return dict(c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())


@router.post("/{doc_id}/reindex", status_code=202)
def reindex(doc_id: int):
    with session() as c:
        _doc_or_404(c, doc_id)
    try:
        return {"job_id": jobs.start("reindex", lambda ctx: indexer.reindex_documents(ctx, [doc_id]))}
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/{doc_id}/resolve-page")
def resolve_printed_page(doc_id: int, printed: str):
    """Printed page number -> physical page index (for 'open p. 812')."""
    with session() as c:
        _doc_or_404(c, doc_id)
        rows = c.execute("SELECT page_index, label_src FROM pages WHERE document_id=? AND printed_label=? ORDER BY page_index",
                         (doc_id, printed.strip())).fetchall()
    return {"printed": printed, "matches": [dict(r) for r in rows]}


@router.get("/{doc_id}/pages/{page_index}")
def get_page(doc_id: int, page_index: int):
    with session() as c:
        d = _doc_or_404(c, doc_id)
        p = c.execute("SELECT * FROM pages WHERE document_id=? AND page_index=?", (doc_id, page_index)).fetchone()
        if p is None:
            raise HTTPException(404, "page not indexed")
        text = citations.page_text(c, doc_id, page_index)
    return {"document_id": doc_id, "page_index": page_index, "page_count": d["page_count"],
            "renderable": d["ext"] in RENDERABLE, "text": text, "page": dict(p),
            "citation": citations.build(d, p, page_index)}


@router.get("/{doc_id}/pages/{page_index}/image")
def page_image(doc_id: int, page_index: int, highlight: str | None = None, dpi: int | None = Query(None, ge=50, le=300)):
    with session() as c:
        d = _doc_or_404(c, doc_id)
    if d["ext"] not in RENDERABLE:
        raise HTTPException(415, "this format has no page images")
    local = _local_or_error(d)
    doc = pymupdf.open(os_path(local))  # in-memory annotations only; the file is never saved
    try:
        if not 0 <= page_index < doc.page_count:
            raise HTTPException(404, "page out of range")
        page = doc.load_page(page_index)
        if highlight:
            terms = [t.strip() for t in re.split(r"[|\n]", highlight) if len(t.strip()) >= 3][:12]
            for t in terms:
                quads = page.search_for(t, quads=True)
                if quads:
                    annot = page.add_highlight_annot(quads)
                    annot.set_colors(stroke=(0.36, 0.85, 0.82))
                    annot.update()
        pix = page.get_pixmap(dpi=dpi or get_settings().page_image_dpi, annots=True)
        png = pix.tobytes("png")
    finally:
        doc.close()
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{doc_id}/file")
def original_file(doc_id: int):
    """Streams the original (read-only). Append #page=N in a PDF viewer to jump to a page."""
    with session() as c:
        d = _doc_or_404(c, doc_id)
    local = _local_or_error(d)
    mt = mimetypes.guess_type(d["filename"])[0] or "application/octet-stream"
    return FileResponse(os_path(local), media_type=mt, filename=d["filename"], content_disposition_type="inline")


def _local_or_error(d) -> str:
    """Local path of the original; Drive files are served from (and if needed downloaded into) the cache."""
    if gdrive.is_drive(d["path"]):
        try:
            return gdrive.local_copy(d)
        except gdrive.DriveError as e:
            raise HTTPException(410, f"Google Drive file unavailable: {e}") from e
    if not os.path.isfile(os_path(d["path"])):
        raise HTTPException(410, "file is no longer on disk")
    return d["path"]
