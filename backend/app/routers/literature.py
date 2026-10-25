from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import audit, now_iso, session
from ..services import literature as lit

router = APIRouter(prefix="/api/literature", tags=["literature"])

DESIGN_GROUPS = {
    "synthesis": ("Guideline / consensus", "Systematic review / meta-analysis"),
    "trials": ("Randomized controlled trial", "Prospective study / clinical trial"),
    "observational": ("Observational study", "Case series"),
    "preliminary": ("Case report", "Technical note", "Preprint (not peer reviewed)"),
    "reviews": ("Narrative review", "Editorial / letter / comment"),
}


def _items(c, where: str, params: list, limit: int, offset: int) -> dict:
    total = c.execute(f"SELECT COUNT(*) FROM publications p WHERE {where}", params).fetchone()[0]
    rows = c.execute(
        f"""SELECT p.*, (SELECT group_concat(t.name, '|') FROM topic_hits h JOIN topics t ON t.id=h.topic_id
                       WHERE h.publication_id=p.id) AS topic_names
            FROM publications p WHERE {where}
            ORDER BY COALESCE(p.pub_date, '') DESC, p.id DESC LIMIT ? OFFSET ?""",
        (*params, limit, offset)).fetchall()
    items = []
    for r in rows:
        d = lit.pub_row(r)
        d["topics"] = [x for x in (d.pop("topic_names") or "").split("|") if x]
        items.append(d)
    return {"total": total, "items": items}


def _filters(design: str | None, oa: bool, unreviewed: bool, text: str | None) -> tuple[list[str], list]:
    where, params = [], []
    if design and design in DESIGN_GROUPS:
        g = DESIGN_GROUPS[design]
        where.append(f"p.design IN ({','.join('?' * len(g))})")
        params += list(g)
    if oa:
        where.append("p.is_oa=1")
    if unreviewed:
        where.append("p.reviewed=0")
    if text:
        where.append("(p.title LIKE ? OR p.abstract LIKE ? OR p.journal LIKE ?)")
        params += [f"%{text}%"] * 3
    return where, params


@router.get("/feed")
def feed(topic_id: int | None = None, days: int = Query(7, ge=1, le=3650), date_from: str | None = None,
         date_to: str | None = None, design: str | None = None, oa: bool = False, unreviewed: bool = False,
         text: str | None = None, limit: int = Query(50, le=500), offset: int = 0):
    start = date_from or (date.today() - timedelta(days=days)).isoformat()
    where = ["p.pub_date >= ?", "EXISTS (SELECT 1 FROM topic_hits h WHERE h.publication_id=p.id"
             + (" AND h.topic_id=?" if topic_id else "") + ")"]
    params: list = [start] + ([topic_id] if topic_id else [])
    if date_to:
        where.append("p.pub_date <= ?")
        params.append(date_to)
    w2, p2 = _filters(design, oa, unreviewed, text)
    with session() as c:
        res = _items(c, " AND ".join(where + w2), params + p2, limit, offset)
        ok = c.execute("SELECT * FROM search_runs WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
        last = c.execute("SELECT * FROM search_runs ORDER BY id DESC LIMIT 1").fetchone()
    res["window_from"] = start
    res["last_ok"] = dict(ok) if ok else None
    res["last_error"] = dict(last) if last and last["status"] == "error" else None
    res["run_state"] = lit.run_state
    return res


@router.get("/search")
def live_search(q: str = Query(..., min_length=2, max_length=600), date_from: str | None = None,
                date_to: str | None = None, oa: bool = False, preprints: bool = False, fields: str = "tiab",
                design: str | None = None, limit: int = Query(100, le=300)):
    started = now_iso()
    try:
        pubs, source, warning = lit.search(q, date_from, date_to, oa_only=oa, include_preprints=preprints,
                                           fields="all" if fields == "all" else "tiab", limit=limit)
    except lit.SourceError as e:
        with session() as c:
            c.execute("INSERT INTO search_runs(query, window_from, window_to, started_at, finished_at, status, error) "
                      "VALUES (?,?,?,?,?, 'error', ?)", (q, date_from, date_to, started, now_iso(), str(e)))
        raise HTTPException(502, f"Literature sources unavailable: {e}") from e
    with session() as c:
        ids = [pid for pid, _ in lit.upsert(c, pubs)]
        c.execute("INSERT INTO search_runs(query, window_from, window_to, source, started_at, finished_at, status, "
                  "found, new, error) VALUES (?,?,?,?,?,?, 'ok', ?, NULL, ?)",
                  (q, date_from, date_to, source, started, now_iso(), len(pubs), warning))
        if not ids:
            return {"source": source, "warning": warning, "searched_at": now_iso(), "total": 0, "items": []}
        w2, p2 = _filters(design, False, False, None)
        where = [f"p.id IN ({','.join('?' * len(ids))})"] + w2
        res = _items(c, " AND ".join(where), ids + p2, 500, 0)
    return {"source": source, "warning": warning, "searched_at": now_iso(), **res}


class TopicIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    query: str = Field(..., min_length=2, max_length=2000)


class TopicPatch(BaseModel):
    name: str | None = None
    query: str | None = None
    enabled: bool | None = None


@router.get("/topics")
def topics():
    with session() as c:
        rows = c.execute("""
            SELECT t.*, COUNT(h.publication_id) AS total,
                   SUM(CASE WHEN p.reviewed=0 THEN 1 ELSE 0 END) AS unreviewed,
                   (SELECT status FROM search_runs r WHERE r.topic_id=t.id ORDER BY r.id DESC LIMIT 1) AS last_status,
                   (SELECT error FROM search_runs r WHERE r.topic_id=t.id ORDER BY r.id DESC LIMIT 1) AS last_error
            FROM topics t LEFT JOIN topic_hits h ON h.topic_id=t.id LEFT JOIN publications p ON p.id=h.publication_id
            GROUP BY t.id ORDER BY t.id""").fetchall()
    return [dict(r) for r in rows]


@router.post("/topics", status_code=201)
def add_topic(body: TopicIn):
    with session() as c:
        if c.execute("SELECT 1 FROM topics WHERE name=?", (body.name.strip(),)).fetchone():
            raise HTTPException(409, "A topic with this name exists")
        cur = c.execute("INSERT INTO topics(name, query, enabled, builtin, created_at) VALUES (?,?,1,0,?)",
                        (body.name.strip(), body.query.strip(), now_iso()))
        audit(c, "topic.added", body.name)
        return dict(c.execute("SELECT * FROM topics WHERE id=?", (cur.lastrowid,)).fetchone())


@router.patch("/topics/{topic_id}")
def patch_topic(topic_id: int, body: TopicPatch):
    with session() as c:
        if not c.execute("SELECT 1 FROM topics WHERE id=?", (topic_id,)).fetchone():
            raise HTTPException(404)
        if body.name is not None:
            c.execute("UPDATE topics SET name=? WHERE id=?", (body.name.strip(), topic_id))
        if body.query is not None:
            # A new query means a new search window from scratch.
            c.execute("UPDATE topics SET query=?, last_run_at=NULL WHERE id=?", (body.query.strip(), topic_id))
        if body.enabled is not None:
            c.execute("UPDATE topics SET enabled=? WHERE id=?", (int(body.enabled), topic_id))
        return dict(c.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone())


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: int):
    with session() as c:
        c.execute("DELETE FROM topics WHERE id=?", (topic_id,))
    return {"deleted": True}


@router.post("/topics/{topic_id}/run")
def run_topic(topic_id: int, days: int | None = Query(None, ge=1, le=3650)):
    try:
        res = lit.run_topic(topic_id, days=days)
    except KeyError as e:
        raise HTTPException(404) from e
    if res["status"] == "error":
        raise HTTPException(502, f"Literature sources unavailable: {res['error']}")
    return res


@router.post("/run", status_code=202)
def run_all():
    return {"started": lit.run_all_async(only_due=False), "state": lit.run_state}


@router.get("/run-state")
def run_state():
    return lit.run_state


class PubPatch(BaseModel):
    reviewed: bool | None = None
    saved: bool | None = None


@router.patch("/publications/{pub_id}")
def patch_pub(pub_id: int, body: PubPatch):
    with session() as c:
        if body.reviewed is not None:
            c.execute("UPDATE publications SET reviewed=? WHERE id=?", (int(body.reviewed), pub_id))
        if body.saved is not None:
            c.execute("UPDATE publications SET saved=? WHERE id=?", (int(body.saved), pub_id))
        r = c.execute("SELECT * FROM publications WHERE id=?", (pub_id,)).fetchone()
    if r is None:
        raise HTTPException(404)
    return lit.pub_row(r)


class MarkIn(BaseModel):
    ids: list[int] = []


@router.post("/publications/mark-reviewed")
def mark_reviewed(body: MarkIn):
    if not body.ids:
        return {"updated": 0}
    with session() as c:
        cur = c.execute(f"UPDATE publications SET reviewed=1 WHERE id IN ({','.join('?' * len(body.ids))})", body.ids)
    return {"updated": cur.rowcount}


@router.post("/publications/{pub_id}/add-to-library")
def add_to_library(pub_id: int):
    try:
        res = lit.add_to_library(pub_id)
    except KeyError as e:
        raise HTTPException(404) from e
    except lit.SourceError as e:
        raise HTTPException(422, str(e)) from e
    return res


@router.get("/saved")
def saved(limit: int = Query(200, le=1000)):
    with session() as c:
        return _items(c, "p.saved=1", [], limit, 0)


@router.get("/runs")
def runs(limit: int = Query(30, le=200)):
    with session() as c:
        rows = c.execute("""SELECT r.*, t.name AS topic FROM search_runs r LEFT JOIN topics t ON t.id=r.topic_id
                            ORDER BY r.id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/selftest")
def selftest():
    return lit.selftest()
