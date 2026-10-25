from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..db import session
from ..services import citations, semantic
from ..services import search as search_svc

router = APIRouter(prefix="/api", tags=["search"])
log = logging.getLogger(__name__)


def _ids(s: str | None) -> list[int] | None:
    if not s:
        return None
    try:
        return [int(x) for x in s.split(",") if x.strip()]
    except ValueError as e:
        raise HTTPException(400, "ids must be comma-separated integers") from e


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=500), limit: int = Query(20, ge=1, le=100),
           max_per_doc: int = Query(4, ge=1, le=50), doc_ids: str | None = None, folder_ids: str | None = None,
           verified_only: bool = False, semantic_search: bool = True):
    d_ids, f_ids = _ids(doc_ids), _ids(folder_ids)
    sem_ids = None
    sem_error = None
    sem = semantic.get() if semantic_search else None
    if sem is not None:
        try:
            sem_ids = sem.query(q, limit=limit * 3, doc_ids=d_ids)
        except Exception as e:  # noqa: BLE001 - degrade to lexical, but say so
            sem_error = str(e)
            log.warning("semantic query failed: %s", e)
    with session() as c:
        res = search_svc.search(c, q, limit=limit, max_per_doc=max_per_doc, doc_ids=d_ids, folder_ids=f_ids,
                                verified_only=verified_only, semantic_ids=sem_ids)
    res["semantic_error"] = sem_error
    res["coverage_note"] = None if res["hits"] else (
        "No supporting passage found in the indexed library. The answer cannot be grounded in your books.")
    return res


class VerifyIn(BaseModel):
    document_id: int
    page_index: int
    quote: str


@router.post("/citations/verify")
def verify(body: VerifyIn):
    with session() as c:
        if not c.execute("SELECT 1 FROM documents WHERE id=? AND status IN ('indexed','partial','ocr_needed')",
                         (body.document_id,)).fetchone():
            return {"verified": False, "reason": "document is not indexed; it cannot be cited"}
        return citations.verify_quote(c, body.document_id, body.page_index, body.quote)
