from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..config import get_settings
from ..db import session
from ..services import extractor, gdrive, jobs, semantic, watcher

public = APIRouter(prefix="/api", tags=["system"])
router = APIRouter(prefix="/api", tags=["system"])


@public.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/status")
def status():
    s = get_settings()
    return {
        "version": __version__,
        "ocr_available": extractor.ocr_available(),
        "semantic_enabled": semantic.get() is not None,
        "embedding_model": s.embedding_model if s.semantic_enabled else None,
        "active_job": jobs.active_job(),
        "data_dir": str(s.data_dir),
        "phase": 1,
        "auto_indexing": watcher.running(),
        "auto_indexing_interval": s.watch_interval_seconds,
        "auto_indexing_state": watcher.state,
        "local_folders_enabled": s.local_folders_enabled,
        "uploads_enabled": s.uploads_enabled,
        "gdrive": gdrive.status(),
    }


@router.get("/stats")
def stats():
    with session() as c:
        by_status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM documents GROUP BY status")}
        agg = c.execute("""SELECT COALESCE(SUM(page_count),0) pages, COALESCE(SUM(chunk_count),0) chunks,
                                  COALESCE(SUM(ocr_pages),0) ocr_pages
                           FROM documents WHERE status IN ('indexed','partial','ocr_needed')""").fetchone()
        recent = c.execute("""SELECT id, title, filename, indexed_at, page_count FROM documents
                              WHERE status IN ('indexed','partial','ocr_needed')
                              ORDER BY indexed_at DESC LIMIT 8""").fetchall()
        recent_7d = c.execute("SELECT COUNT(*) FROM documents WHERE added_at >= datetime('now','-7 days')").fetchone()[0]
        folders = c.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
        last_scan = c.execute("SELECT MAX(last_scan_at) FROM folders").fetchone()[0]
        verified = c.execute("SELECT COUNT(*) FROM documents WHERE metadata_verified=1").fetchone()[0]
        new_pubs = c.execute("SELECT COUNT(*) FROM publications p WHERE p.reviewed=0 AND EXISTS "
                             "(SELECT 1 FROM topic_hits h WHERE h.publication_id=p.id)").fetchone()[0]
        lit_last = c.execute("SELECT MAX(finished_at) FROM search_runs WHERE status='ok'").fetchone()[0]
    indexed = sum(by_status.get(k, 0) for k in ("indexed", "partial", "ocr_needed"))
    return {
        "indexed_documents": indexed,
        "verified_metadata": verified,
        "pages": agg["pages"],
        "chunks": agg["chunks"],
        "ocr_pages": agg["ocr_pages"],
        "by_status": by_status,
        "folders": folders,
        "last_scan_at": last_scan,
        "added_last_7_days": recent_7d,
        "recent": [dict(r) for r in recent],
        # Modules not delivered yet report null rather than fabricated zeros.
        "questions_generated": None,
        "saved_lectures": None,
        "new_publications": new_pubs,
        "literature_last_update": lit_last,
    }


@router.get("/quality-report")
def quality_report():
    with session() as c:
        rows = c.execute("""SELECT id, filename, title, status, page_count, text_pages, ocr_pages, empty_pages,
                                   label_mode, has_toc, quality_score, quality_notes, error, metadata_verified,
                                   possible_duplicate_of, duplicate_of
                            FROM documents WHERE status <> 'missing'
                            ORDER BY CASE status WHEN 'error' THEN 0 WHEN 'ocr_needed' THEN 1 WHEN 'partial' THEN 2
                                     ELSE 3 END, quality_score""").fetchall()
    return [dict(r) for r in rows]


@router.get("/audit")
def audit_log(limit: int = 200):
    with session() as c:
        return [dict(r) for r in c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]
