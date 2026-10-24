"""Printed page-number resolution.

A textbook PDF's physical page index almost never equals the printed page number (covers, front matter,
inserted plates). Citations must use the printed number, so for every page we resolve it as:

1. Embedded PDF page labels (/PageLabels) - authoritative when present.
2. Inferred from running headers/footers: each page votes for an offset (printed - physical) from
   standalone numbers in its first/last lines; a page receives a label only if a local window of
   neighbouring pages agrees on the same offset. Labels obtained this way are marked `inferred`.
3. Otherwise no printed label; citations fall back to "PDF p. N" explicitly.
"""
from __future__ import annotations

import re
from collections import Counter

RE_STANDALONE_NUM = re.compile(r"^\s*(?:page\s+)?(\d{1,4})\s*$", re.I)
RE_EDGE_NUM = re.compile(r"(?:^|\s)(\d{1,4})(?:\s|$)")

WINDOW = 12           # pages either side
MIN_VOTES = 3         # agreeing neighbours required
MIN_SHARE = 0.5       # of the voting neighbours


def edge_candidates(text: str) -> set[int]:
    """Numbers appearing alone, or at the start/end, of the first and last two non-empty lines."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return set()
    edge = lines[:2] + lines[-2:]
    found: set[int] = set()
    for ln in edge:
        m = RE_STANDALONE_NUM.match(ln)
        if m:
            found.add(int(m.group(1)))
            continue
        if len(ln) > 120:
            continue
        toks = ln.split()
        for tok in (toks[0], toks[-1]):
            if tok.isdigit() and len(tok) <= 4:
                found.add(int(tok))
    return {n for n in found if 1 <= n <= 5000}


def infer_offsets(page_texts: list[str]) -> list[int | None]:
    """Return per-page offset (printed = physical_index + 1 + offset) or None."""
    n = len(page_texts)
    votes: list[set[int]] = []
    for i, txt in enumerate(page_texts):
        votes.append({num - (i + 1) for num in edge_candidates(txt)})

    result: list[int | None] = [None] * n
    for i in range(n):
        lo, hi = max(0, i - WINDOW), min(n, i + WINDOW + 1)
        counter: Counter[int] = Counter()
        voters = 0
        for j in range(lo, hi):
            if votes[j]:
                voters += 1
                counter.update(votes[j])
        if not counter:
            continue
        off, cnt = counter.most_common(1)[0]
        if cnt >= MIN_VOTES and cnt / max(voters, 1) >= MIN_SHARE and (i + 1 + off) >= 1:
            result[i] = off
    return result


def resolve_labels(embedded: list[str], page_texts: list[str]) -> tuple[list[tuple[str | None, str | None]], str]:
    """Returns [(label, source)] per page and an overall mode: embedded|inferred|mixed|none."""
    n = len(page_texts)
    out: list[tuple[str | None, str | None]] = [(None, None)] * n
    has_embedded = any(embedded)
    # Embedded labels that are just "1..N" identical to physical numbering add no information but are
    # still the publisher's labels; we keep them only if they are not trivially identical to index+1
    # across the whole book (some PDF generators write those blindly).
    trivial = has_embedded and all(lbl == str(i + 1) for i, lbl in enumerate(embedded) if lbl)
    if has_embedded and not trivial:
        for i, lbl in enumerate(embedded):
            if lbl:
                out[i] = (lbl, "embedded")

    offsets = infer_offsets(page_texts)
    used_inferred = False
    for i in range(n):
        if out[i][0] is None and offsets[i] is not None:
            out[i] = (str(i + 1 + offsets[i]), "inferred")
            used_inferred = True

    if trivial and not used_inferred:
        # Trivial embedded labels with no contradicting evidence: accept them as embedded.
        out = [(lbl or None, "embedded" if lbl else None) for lbl in embedded]

    labelled_src = {src for _, src in out if src}
    if not labelled_src:
        mode = "none"
    elif labelled_src == {"embedded"}:
        mode = "embedded"
    elif labelled_src == {"inferred"}:
        mode = "inferred"
    else:
        mode = "mixed"
    return out, mode
