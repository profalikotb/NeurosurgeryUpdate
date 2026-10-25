"""Citation construction and verification.

A citation is built only from stored facts: the document's metadata (with provenance), the page's chapter
from the embedded TOC, and the printed page label (embedded, or inferred and flagged). Anything unknown is
omitted rather than filled in.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from typing import Any


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("­", "")
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"[‘’]", "'", s)
    s = re.sub(r"[“”]", '"', s)
    s = re.sub(r"-\s+", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def build(doc: sqlite3.Row | dict[str, Any], page: sqlite3.Row | dict[str, Any] | None, page_index: int) -> dict[str, Any]:
    d = dict(doc)
    p = dict(page) if page is not None else {}
    reflowable = bool(d.get("reflowable"))
    printed = p.get("printed_label")
    printed_src = p.get("label_src")
    chapter = p.get("chapter")
    section = p.get("section")

    parts: list[str] = []
    if d.get("authors"):
        parts.append(d["authors"].rstrip(".") + ".")
    if d.get("title"):
        parts.append(d["title"].rstrip(".") + ".")
    if d.get("edition"):
        parts.append(f"{d['edition']} ed.")
    pub_year = ", ".join(x for x in [d.get("publisher"), str(d["year"]) if d.get("year") else None] if x)
    if pub_year:
        parts.append(pub_year + ".")
    if chapter:
        parts.append(f"Chapter: {chapter}.")
    if reflowable:
        loc = f"Section {page_index + 1}"
    elif printed:
        loc = f"p. {printed}" + (" (page number inferred)" if printed_src == "inferred" else "") + f" [PDF p. {page_index + 1}]"
    else:
        loc = f"PDF p. {page_index + 1} (printed page number unavailable)"
    parts.append(loc + ".")

    return {
        "document_id": d["id"],
        "filename": d.get("filename"),
        "title": d.get("title"),
        "authors": d.get("authors"),
        "edition": d.get("edition"),
        "year": d.get("year"),
        "publisher": d.get("publisher"),
        "isbn": d.get("isbn"),
        "metadata_verified": bool(d.get("metadata_verified")),
        "metadata_sources": {k: d.get(f"{k}_src") for k in ("title", "authors", "edition", "year", "publisher", "isbn")
                             if d.get(f"{k}_src")},
        "chapter": chapter,
        "section": section,
        "page_index": page_index,
        "pdf_page": page_index + 1,
        "printed_page": printed,
        "printed_page_source": printed_src,
        "reflowable": reflowable,
        "ocr": bool(p.get("ocr")),
        "formatted": " ".join(parts),
    }


def page_text(conn: sqlite3.Connection, doc_id: int, page_index: int) -> str:
    rows = conn.execute("SELECT text FROM chunks WHERE document_id=? AND page_index=? ORDER BY chunk_no",
                        (doc_id, page_index)).fetchall()
    return "\n".join(r["text"] for r in rows)


def verify_quote(conn: sqlite3.Connection, doc_id: int, page_index: int, quote: str,
                 threshold: float = 0.88, search_neighbours: bool = True) -> dict[str, Any]:
    """Checks that `quote` actually appears on the cited page (exact after normalisation, else fuzzy).
    Neighbouring pages are checked to catch off-by-one citations, which are reported, not silently fixed."""
    q = _norm(quote)
    if len(q) < 8:
        return {"verified": False, "reason": "quote too short to verify", "score": 0.0}

    def best_on(pi: int) -> float:
        txt = _norm(page_text(conn, doc_id, pi))
        if not txt:
            return 0.0
        if q in txt:
            return 1.0
        sm = SequenceMatcher(None, txt, q, autojunk=False)
        m = sm.find_longest_match(0, len(txt), 0, len(q))
        if m.size == 0:
            return 0.0
        anchor = m.a - m.b
        best = 0.0
        for shift in range(-12, 13, 2):
            start = max(0, anchor + shift)
            for extra in (-4, 0, 4):
                window = txt[start:start + len(q) + extra]
                best = max(best, SequenceMatcher(None, window, q, autojunk=False).ratio())
        return best

    score = best_on(page_index)
    if score >= threshold:
        return {"verified": True, "score": round(score, 3), "page_index": page_index,
                "match": "exact" if score == 1.0 else "fuzzy"}
    if search_neighbours:
        for pi in (page_index - 1, page_index + 1):
            if pi >= 0:
                s2 = best_on(pi)
                if s2 >= threshold:
                    return {"verified": False, "score": round(s2, 3), "page_index": pi,
                            "reason": f"text found on PDF p. {pi + 1}, not on the cited page"}
    return {"verified": False, "score": round(score, 3), "reason": "text not found on the cited page"}
