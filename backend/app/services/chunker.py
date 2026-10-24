"""Page-bounded chunking and TOC-to-page chapter mapping."""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z؀-ۿ(\[])")


def chunk_page(text: str, size: int, overlap: int) -> list[str]:
    """Split one page into chunks of ~size chars on paragraph/sentence boundaries; never crosses pages."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            units.append(para)
        else:
            units.extend(s for s in _SENT_SPLIT.split(para) if s.strip())
    chunks: list[str] = []
    cur = ""
    for u in units:
        while len(u) > size:  # pathological unbroken block (tables, OCR noise)
            cut = u.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(u[:cut].strip())
            u = u[cut:].strip()
        if not cur:
            cur = u
        elif len(cur) + 1 + len(u) <= size:
            cur = f"{cur}\n{u}"
        else:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            sp = tail.find(" ")
            tail = tail[sp + 1:] if sp != -1 else tail
            cur = f"{tail} {u}".strip() if tail else u
    if cur:
        chunks.append(cur)
    return chunks


def chapter_map(toc: list[tuple[int, str, int]], page_count: int) -> list[tuple[str | None, str | None]]:
    """Returns (chapter, section) per page.

    Chapter level is the top TOC level, unless the top level is just the book/part wrapper
    (<= 3 entries while the next level has many), in which case level 2 is used.
    Section = the deepest heading starting on or before the page.
    """
    result: list[tuple[str | None, str | None]] = [(None, None)] * page_count
    if not toc:
        return result
    levels = sorted({lvl for lvl, _, _ in toc})
    chap_level = levels[0]
    top = [t for t in toc if t[0] == levels[0]]
    if len(levels) > 1:
        nxt = [t for t in toc if t[0] == levels[1]]
        if len(top) <= 3 and len(nxt) >= 5:
            chap_level = levels[1]
    entries = sorted(toc, key=lambda t: (t[2], t[0]))
    chapter: str | None = None
    section: str | None = None
    idx = 0
    for p in range(page_count):
        while idx < len(entries) and entries[idx][2] <= p:
            lvl, title, _ = entries[idx]
            if lvl <= chap_level:
                chapter = title if lvl == chap_level else chapter
                if lvl < chap_level:
                    chapter = None
                section = None
            else:
                section = title
            idx += 1
        result[p] = (chapter, section)
    return result


def toc_with_ends(toc: list[tuple[int, str, int]], page_count: int) -> list[tuple[int, str, int, int]]:
    out = []
    for i, (lvl, title, start) in enumerate(toc):
        end = page_count - 1
        for lvl2, _, start2 in toc[i + 1:]:
            if lvl2 <= lvl:
                end = max(start, start2 - 1)
                break
        out.append((lvl, title, start, end))
    return out


_ROMAN = re.compile(r"^(?=[ivxlcdm]+$)m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.I)


def _edge_key(line: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.strip().lower()))


def strip_running_lines(texts: list[str], edge: int = 2) -> list[str]:
    """Removes running headers/footers and bare page numbers so they do not pollute passages and ranking.

    An edge line (first/last `edge` non-empty lines) is removed when, with digits normalised, the same short
    line recurs at page edges on >= max(3, 15%) of pages; bare numbers/roman numerals at edges are always removed.
    Printed page numbers are resolved before this step, from the raw text.
    """
    n = len(texts)
    split = [[ln for ln in t.splitlines()] for t in texts]
    counts: dict[str, int] = {}
    for lines in split:
        nz = [ln for ln in lines if ln.strip()]
        e = edge if len(nz) > 2 * edge else 1
        for ln in set(nz[:e] + nz[-e:]):
            if len(ln.strip()) <= 90:
                k = _edge_key(ln)
                counts[k] = counts.get(k, 0) + 1
    threshold = max(3, int(0.15 * n)) if n >= 6 else 10**9
    frequent = {k for k, c in counts.items() if c >= threshold and k.strip("# ")}
    out = []
    for lines in split:
        idx = [i for i, ln in enumerate(lines) if ln.strip()]
        e = edge if len(idx) > 2 * edge else 1
        edges = set(idx[:e] + idx[-e:])
        kept = []
        for i, ln in enumerate(lines):
            s = ln.strip()
            if i in edges and (_edge_key(ln) in frequent or s.isdigit() and len(s) <= 4 or _ROMAN.match(s or "-")):
                continue
            kept.append(ln)
        out.append("\n".join(kept).strip())
    return out
