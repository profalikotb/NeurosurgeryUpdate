"""Library search: FTS5/BM25 with neurosurgical synonym expansion, optional semantic fusion (RRF).

Returned hits are always grounded: each carries the exact chunk text, its page, and a citation built
from stored metadata only.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from . import citations, synonyms

STOPWORDS = set("""
a an and are as at be been being but by can could do does did for from had has have how i if in into is it its
may might of on or should than that the their them then there these this those to was were what when where which
while who whom why will with would you your about between versus vs describe discuss explain compare list
""".split())
MARK_OPEN, MARK_CLOSE = "", ""
_FTS_UNSAFE = re.compile(r'[^\w\s\-؀-ۿ*]')


@dataclass
class ParsedQuery:
    groups: list[list[str]]          # each group = equivalent terms (OR); groups combined with AND / OR
    highlight_terms: list[str]


def parse(q: str) -> ParsedQuery:
    q = q.strip()
    groups: list[list[str]] = []
    for ph in re.findall(r'"([^"]+)"', q):
        ph = _FTS_UNSAFE.sub(" ", ph).strip()
        if ph:
            groups.append(synonyms.expand(ph))
    rest = re.sub(r'"[^"]*"', " ", q)
    rest = _FTS_UNSAFE.sub(" ", rest)
    low = " " + re.sub(r"\s+", " ", rest.lower()) + " "
    for ph in synonyms.phrases():
        needle = f" {ph} "
        if needle in low:
            groups.append(synonyms.expand(ph))
            low = low.replace(needle, " ")
    for tok in low.split():
        tok = tok.strip("-")
        if not tok.strip("*"):
            continue
        tok = tok if tok.count("*") <= 1 and (tok.endswith("*") or "*" not in tok) else tok.replace("*", "")
        if not tok or tok in STOPWORDS or (len(tok) < 2 and not tok.isdigit()):
            continue
        # preserve the user's original casing for abbreviation lookup
        groups.append(synonyms.expand(tok))
    # de-duplicate groups
    seen: set[tuple[str, ...]] = set()
    uniq = []
    for g in groups:
        key = tuple(sorted(x.lower() for x in g))
        if key not in seen:
            seen.add(key)
            uniq.append(g)
    hl = sorted({t for g in uniq for t in g}, key=len, reverse=True)
    return ParsedQuery(uniq, hl)


def _term(t: str) -> str:
    t = t.replace('"', "")
    if t.endswith("*") and " " not in t:
        return f'"{t[:-1]}"*'
    return f'"{t}"'


def to_fts(pq: ParsedQuery, mode: str) -> str:
    parts = []
    for g in pq.groups:
        terms = [_term(t) for t in g]
        parts.append(terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")")
    return f" {mode} ".join(parts)


def _filters(doc_ids: list[int] | None, folder_ids: list[int] | None, verified_only: bool) -> tuple[str, list]:
    sql, params = "", []
    if doc_ids:
        sql += f" AND c.document_id IN ({','.join('?' * len(doc_ids))})"
        params += doc_ids
    if folder_ids:
        sql += f" AND d.folder_id IN ({','.join('?' * len(folder_ids))})"
        params += folder_ids
    if verified_only:
        sql += " AND d.metadata_verified = 1"
    return sql, params


def lexical(conn: sqlite3.Connection, pq: ParsedQuery, limit: int, doc_ids=None, folder_ids=None,
            verified_only=False) -> list[dict[str, Any]]:
    if not pq.groups:
        return []
    fsql, fparams = _filters(doc_ids, folder_ids, verified_only)
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    modes = ["AND", "OR"] if len(pq.groups) > 1 else ["AND"]
    for mode in modes:
        expr = to_fts(pq, mode)
        rows = conn.execute(
            f"""SELECT c.id, c.document_id, c.page_index, c.chunk_no, c.text,
                       bm25(chunks_fts, 1.0, 2.0, 1.5) AS score,
                       snippet(chunks_fts, 0, '{MARK_OPEN}', '{MARK_CLOSE}', ' … ', 48) AS snip
                FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
                JOIN documents d ON d.id = c.document_id
                WHERE chunks_fts MATCH ? AND d.status IN ('indexed','partial','ocr_needed') {fsql}
                ORDER BY score LIMIT ?""",
            (expr, *fparams, limit * 3),
        ).fetchall()
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            results.append({**dict(r), "match": "all_terms" if mode == "AND" else "some_terms"})
        if len(results) >= limit:
            break
    return results


def rrf(lists: list[list[int]], k: int = 60) -> dict[int, float]:
    scores: dict[int, float] = {}
    for lst in lists:
        for rank, cid in enumerate(lst):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


def search(conn: sqlite3.Connection, q: str, limit: int = 20, max_per_doc: int = 4, doc_ids=None, folder_ids=None,
           verified_only: bool = False, semantic_ids: list[int] | None = None) -> dict[str, Any]:
    pq = parse(q)
    lex = lexical(conn, pq, limit * 2, doc_ids, folder_ids, verified_only)
    by_id = {r["id"]: r for r in lex}
    order = [r["id"] for r in lex]
    if semantic_ids:
        fused = rrf([order, semantic_ids])
        order = sorted(fused, key=fused.get, reverse=True)
        missing = [cid for cid in order if cid not in by_id]
        if missing:
            for r in conn.execute(f"SELECT id, document_id, page_index, chunk_no, text FROM chunks WHERE id IN "
                                  f"({','.join('?' * len(missing))})", missing):
                by_id[r["id"]] = {**dict(r), "score": None, "snip": None, "match": "semantic"}

    per_doc: dict[int, int] = {}
    hits: list[dict[str, Any]] = []
    doc_cache: dict[int, sqlite3.Row] = {}
    for cid in order:
        r = by_id.get(cid)
        if r is None:
            continue
        did = r["document_id"]
        if per_doc.get(did, 0) >= max_per_doc:
            continue
        per_doc[did] = per_doc.get(did, 0) + 1
        if did not in doc_cache:
            doc_cache[did] = conn.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
        page = conn.execute("SELECT * FROM pages WHERE document_id=? AND page_index=?", (did, r["page_index"])).fetchone()
        snippet = r.get("snip") or _make_snippet(r["text"], pq.highlight_terms)
        hits.append({
            "chunk_id": cid,
            "document_id": did,
            "page_index": r["page_index"],
            "snippet": snippet,
            "text": r["text"],
            "score": r.get("score"),
            "match": r.get("match"),
            "citation": citations.build(doc_cache[did], page, r["page_index"]),
        })
        if len(hits) >= limit:
            break
    return {"query": q, "expanded_terms": pq.groups, "highlight_terms": pq.highlight_terms,
            "semantic": bool(semantic_ids), "hits": hits}


def _make_snippet(text: str, terms: list[str], width: int = 320) -> str:
    low = text.lower()
    pos = -1
    for t in terms:
        pos = low.find(t.lower())
        if pos != -1:
            break
    start = max(0, pos - width // 3) if pos != -1 else 0
    snip = text[start:start + width]
    for t in terms:
        snip = re.sub(re.escape(t), lambda m: f"{MARK_OPEN}{m.group(0)}{MARK_CLOSE}", snip, flags=re.I)
    return ("… " if start else "") + snip + (" …" if start + width < len(text) else "")
