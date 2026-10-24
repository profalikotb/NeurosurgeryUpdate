"""Folder scanning, change detection, deduplication and document indexing."""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from ..db import audit, now_iso, session
from . import chunker, extractor, metadata, pagelabels, semantic
from .jobs import JobContext
from .paths import is_within, normalize, os_path

log = logging.getLogger(__name__)

SKIP_DIR_NAMES = {"$recycle.bin", "system volume information", ".git", "node_modules", "__pycache__"}
USER_SRC = "user"
META_FIELDS = ("title", "authors", "edition", "year", "publisher", "isbn")


@dataclass
class FoundFile:
    path: str
    size: int
    mtime: float
    folder_id: int


def sha256_file(path: str, cancelled=None) -> str:
    h = hashlib.sha256()
    with open(os_path(path), "rb") as f:
        while True:
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            b = f.read(4 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def discover(folders: list[sqlite3.Row], ctx: JobContext | None = None) -> list[FoundFile]:
    s = get_settings()
    exts = {e.lower() for e in s.supported_extensions}
    max_bytes = s.max_file_mb * 1024 * 1024
    found: dict[str, FoundFile] = {}
    for folder in folders:
        root = folder["path"]
        if not os.path.isdir(os_path(root)):
            if ctx:
                ctx.log(f"Folder not reachable (drive disconnected or network share offline): {root}")
            continue

        def onerror(err: OSError) -> None:
            if ctx:
                ctx.log(f"Cannot read {getattr(err, 'filename', '?')}: {err.strerror}")

        for dirpath, dirnames, filenames in os.walk(os_path(root), onerror=onerror, followlinks=False):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIR_NAMES and not d.startswith(".")]
            for fn in filenames:
                if fn.startswith(("~$", ".")):
                    continue
                ext = Path(fn).suffix.lower()
                if ext not in exts:
                    continue
                full = normalize(os.path.join(dirpath, fn))
                if full in found:  # nested selected folders
                    continue
                try:
                    st = os.stat(os_path(full))
                except OSError as e:
                    if ctx:
                        ctx.log(f"Cannot stat {full}: {e}")
                    continue
                if st.st_size == 0 or st.st_size > max_bytes:
                    if ctx:
                        ctx.log(f"Skipped (size {st.st_size} bytes): {full}")
                    continue
                found[full] = FoundFile(full, st.st_size, st.st_mtime, folder["id"])
            if ctx:
                ctx.update(phase="discovering", discovered=len(found))
                if ctx.cancelled():
                    raise InterruptedError("cancelled")
    return list(found.values())


def _clear_index(c: sqlite3.Connection, doc_id: int) -> None:
    c.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
    c.execute("DELETE FROM pages WHERE document_id=?", (doc_id,))
    c.execute("DELETE FROM toc WHERE document_id=?", (doc_id,))


def reconcile(ctx: JobContext, folder_ids: list[int] | None, force_reindex: bool = False) -> list[int]:
    """Bring the documents table in line with the file system. Returns ids needing (re)indexing."""
    with session() as c:
        q = "SELECT * FROM folders WHERE enabled=1"
        params: tuple = ()
        if folder_ids:
            q += f" AND id IN ({','.join('?' * len(folder_ids))})"
            params = tuple(folder_ids)
        folders = c.execute(q, params).fetchall()
    if not folders:
        ctx.log("No enabled folders to scan.")
        return []

    files = discover(folders, ctx)
    reachable = [f for f in folders if os.path.isdir(os_path(f["path"]))]
    ctx.update(force=True, phase="comparing", discovered=len(files))
    ctx.log(f"Discovered {len(files)} supported files in {len(reachable)}/{len(folders)} reachable folders.")

    with session() as c:
        existing = {r["path"]: r for r in c.execute("SELECT * FROM documents").fetchall()}
    seen = {f.path for f in files}
    # Candidates for "missing": known docs inside reachable scanned folders that were not found.
    vanished = {
        p: r for p, r in existing.items()
        if p not in seen and r["status"] != "missing" and any(is_within(p, f["path"]) for f in reachable)
    }
    vanished_by_hash = {r["sha256"]: r for r in vanished.values() if r["sha256"]}

    to_index: list[int] = []
    stats = {"new": 0, "changed": 0, "unchanged": 0, "moved": 0, "duplicates": 0, "missing": 0, "restored": 0}
    cur_ver = extractor.EXTRACTOR_VERSION
    new_or_changed = [f for f in files if f.path not in existing
                      or existing[f.path]["size"] != f.size or abs(existing[f.path]["mtime"] - f.mtime) > 1
                      or existing[f.path]["status"] in ("pending", "error", "missing")]
    total_hash = len(new_or_changed)
    hashed = 0

    for f in files:
        if ctx.cancelled():
            raise InterruptedError("cancelled")
        row = existing.get(f.path)
        unchanged = row is not None and row["size"] == f.size and abs(row["mtime"] - f.mtime) <= 1
        if unchanged and row["status"] not in ("pending", "error", "missing"):
            stats["unchanged"] += 1
            if (force_reindex or (row["extractor_version"] or 0) < cur_ver) and row["status"] != "duplicate":
                to_index.append(row["id"])
            continue

        hashed += 1
        ctx.update(phase="hashing", hashed=hashed, to_hash=total_hash, current=os.path.basename(f.path))
        try:
            digest = sha256_file(f.path, ctx.cancelled)
        except OSError as e:
            ctx.log(f"Hash failed (file locked or unreadable): {f.path}: {e}")
            continue

        with session() as c:
            if row is not None:
                if row["sha256"] == digest and row["status"] not in ("pending", "error"):
                    c.execute("UPDATE documents SET size=?, mtime=?, status=CASE WHEN status='missing' "
                              "THEN 'indexed' ELSE status END WHERE id=?", (f.size, f.mtime, row["id"]))
                    if row["status"] == "missing":
                        stats["restored"] += 1
                        to_index.append(row["id"])  # its index was removed when it went missing
                    else:
                        stats["unchanged"] += 1
                    continue
                _clear_index(c, row["id"])
                c.execute("UPDATE documents SET size=?, mtime=?, sha256=?, status='pending', duplicate_of=NULL, "
                          "error=NULL WHERE id=?", (f.size, f.mtime, digest, row["id"]))
                stats["changed"] += 1
                to_index.append(row["id"])
                audit(c, "document.changed", f.path)
                continue

            moved = vanished_by_hash.pop(digest, None)
            if moved is not None:
                vanished.pop(moved["path"], None)
                c.execute("UPDATE documents SET path=?, filename=?, folder_id=?, size=?, mtime=? WHERE id=?",
                          (f.path, os.path.basename(f.path), f.folder_id, f.size, f.mtime, moved["id"]))
                stats["moved"] += 1
                audit(c, "document.moved", f"{moved['path']} -> {f.path}")
                continue

            original = c.execute(
                "SELECT id FROM documents WHERE sha256=? AND status NOT IN ('missing','duplicate') ORDER BY id LIMIT 1",
                (digest,)).fetchone()
            cur = c.execute(
                "INSERT INTO documents(folder_id, path, filename, ext, size, mtime, sha256, status, duplicate_of, added_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f.folder_id, f.path, os.path.basename(f.path), Path(f.path).suffix.lower(), f.size, f.mtime, digest,
                 "duplicate" if original else "pending", original["id"] if original else None, now_iso()))
            if original:
                stats["duplicates"] += 1
            else:
                stats["new"] += 1
                to_index.append(cur.lastrowid)

    with session() as c:
        for p, r in vanished.items():
            _clear_index(c, r["id"])
            c.execute("UPDATE documents SET status='missing', chunk_count=0 WHERE id=?", (r["id"],))
            stats["missing"] += 1
            audit(c, "document.missing", p)
            sem = semantic.get()
            if sem is not None:
                try:
                    sem.delete_document(r["id"])
                except Exception as e:  # noqa: BLE001
                    ctx.log(f"Vector delete failed for {p}: {e}")
            # Promote the first present duplicate so the content stays searchable.
            dup = c.execute("SELECT id FROM documents WHERE duplicate_of=? AND status='duplicate' ORDER BY id LIMIT 1",
                            (r["id"],)).fetchone()
            if dup:
                c.execute("UPDATE documents SET status='pending', duplicate_of=NULL WHERE id=?", (dup["id"],))
                c.execute("UPDATE documents SET duplicate_of=? WHERE duplicate_of=? AND id<>?",
                          (dup["id"], r["id"], dup["id"]))
                to_index.append(dup["id"])
        for f in folders:
            c.execute("UPDATE folders SET last_scan_at=? WHERE id=?", (now_iso(), f["id"]))

    ctx.update(force=True, **{f"files_{k}": v for k, v in stats.items()})
    ctx.log("Reconcile: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    return list(dict.fromkeys(to_index))


def _quality(page_count: int, text_pages: int, ocr_pages: int, ocr_skipped: int, label_mode: str,
             has_toc: bool, reflowable: bool) -> tuple[int, list[str]]:
    notes: list[str] = []
    coverage = text_pages / page_count if page_count else 0
    score = round(coverage * 60)
    if coverage < 0.9:
        notes.append(f"Only {coverage:.0%} of pages contain extractable text.")
    if ocr_skipped:
        notes.append(f"{ocr_skipped} image-only pages were not OCRed (OCR unavailable or budget exceeded).")
    if ocr_pages:
        notes.append(f"{ocr_pages} pages were OCRed; verify quotations against the page image.")
        score -= min(10, round(10 * ocr_pages / max(page_count, 1)))
    if reflowable:
        notes.append("Reflowable format (EPUB/DOCX/TXT): citations use section numbers, not printed pages.")
        score += 15
    elif label_mode == "embedded":
        score += 25
    elif label_mode in ("inferred", "mixed"):
        score += 18
        notes.append("Printed page numbers inferred from running headers/footers; spot-check one citation.")
    else:
        notes.append("Printed page numbers unavailable; citations will give PDF page numbers only.")
    if has_toc:
        score += 15
    else:
        notes.append("No embedded table of contents; chapter attribution unavailable.")
    return max(0, min(100, score)), notes


def index_document(doc_id: int, ctx: JobContext | None = None) -> None:
    s = get_settings()
    with session() as c:
        doc = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if doc is None:
        return

    def prog(done: int, total: int) -> None:
        if ctx:
            ctx.update(page=done, pages=total)

    try:
        ex = extractor.extract(doc["path"], doc["ext"], prog, ctx.cancelled if ctx else None)
    except InterruptedError:
        raise
    except Exception as e:  # noqa: BLE001
        with session() as c:
            c.execute("UPDATE documents SET status='error', error=?, indexed_at=? WHERE id=?",
                      (f"{type(e).__name__}: {e}", now_iso(), doc_id))
        if ctx:
            ctx.log(f"ERROR {doc['filename']}: {e}")
        return

    n = len(ex.pages)
    texts = [p.text for p in ex.pages]
    if ex.reflowable:
        labels: list[tuple[str | None, str | None]] = [(None, None)] * n
        label_mode = "reflowable"
    else:
        labels, label_mode = pagelabels.resolve_labels(ex.embedded_labels, texts)
    chapters = chunker.chapter_map(ex.toc, n)
    clean = texts if ex.reflowable else chunker.strip_running_lines(texts)
    front = "\n".join(texts[: min(12, n)])
    meta = metadata.detect(Path(doc["path"]).stem, ex.embedded_meta, front)

    text_pages = sum(1 for t in texts if len(t) >= s.min_text_chars_per_page)
    ocr_pages = sum(1 for p in ex.pages if p.ocr)
    empty_pages = n - text_pages
    quality, notes = _quality(n, text_pages, ocr_pages, ex.ocr_skipped_pages, label_mode, bool(ex.toc), ex.reflowable)
    notes.extend(ex.warnings[:5])

    if n == 0 or text_pages == 0:
        status = "ocr_needed" if ex.ocr_skipped_pages else "error"
    elif ex.ocr_skipped_pages > 0.3 * n:
        status = "ocr_needed"
    elif text_pages < 0.9 * n and not ex.reflowable:
        status = "partial"
    else:
        status = "indexed"

    chunk_rows = []
    for i in range(n):
        ch, sec = chapters[i]
        for k, piece in enumerate(chunker.chunk_page(clean[i], s.chunk_chars, s.chunk_overlap)):
            chunk_rows.append((doc_id, i, k, ch, sec, piece))

    with session() as c:
        _clear_index(c, doc_id)
        c.executemany(
            "INSERT INTO pages(document_id, page_index, printed_label, label_src, chapter, section, char_count, ocr) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(doc_id, i, labels[i][0], labels[i][1], chapters[i][0], chapters[i][1], len(texts[i]), int(ex.pages[i].ocr))
             for i in range(n)])
        c.executemany("INSERT INTO toc(document_id, seq, level, title, start_page, end_page) VALUES (?,?,?,?,?,?)",
                      [(doc_id, k, lvl, t, st, en) for k, (lvl, t, st, en) in enumerate(chunker.toc_with_ends(ex.toc, n))])
        c.executemany("INSERT INTO chunks(document_id, page_index, chunk_no, chapter, section, text) VALUES (?,?,?,?,?,?)",
                      chunk_rows)

        # Metadata: never overwrite fields the user has set or verified.
        cur = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        sets, vals = [], []
        for fld in META_FIELDS:
            if cur[f"{fld}_src"] == USER_SRC:
                continue
            sets += [f"{fld}=?", f"{fld}_src=?"]
            vals += [meta.values.get(fld), meta.sources.get(fld)]
        sets += ["status=?", "page_count=?", "text_pages=?", "ocr_pages=?", "empty_pages=?", "chunk_count=?",
                 "label_mode=?", "reflowable=?", "has_toc=?", "quality_score=?", "quality_notes=?", "error=NULL",
                 "extractor_version=?", "indexed_at=?"]
        vals += [status, n, text_pages, ocr_pages, empty_pages, len(chunk_rows), label_mode, int(ex.reflowable),
                 int(bool(ex.toc)), quality, "\n".join(notes), extractor.EXTRACTOR_VERSION, now_iso()]
        c.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id=?", (*vals, doc_id))

        # Bibliographic near-duplicate (different file, same title+edition, similar length): flag only.
        row = c.execute("SELECT title, edition, page_count FROM documents WHERE id=?", (doc_id,)).fetchone()
        key = metadata.normalized_title_key(row["title"], row["edition"])
        c.execute("UPDATE documents SET possible_duplicate_of=NULL WHERE id=?", (doc_id,))
        if key:
            for other in c.execute("SELECT id, title, edition, page_count FROM documents WHERE id<>? AND "
                                   "status IN ('indexed','partial','ocr_needed')", (doc_id,)):
                if metadata.normalized_title_key(other["title"], other["edition"]) == key and other["page_count"] \
                        and abs(other["page_count"] - n) <= max(3, 0.03 * n):
                    c.execute("UPDATE documents SET possible_duplicate_of=? WHERE id=?", (other["id"], doc_id))
                    break
        audit(c, "document.indexed", f"{doc['path']} pages={n} chunks={len(chunk_rows)} status={status}")
    sem = semantic.get()
    if sem is not None and chunk_rows:
        try:
            with session() as c:
                sem.index_document(c, doc_id, get_settings().embedding_batch)
        except Exception as e:  # noqa: BLE001 - lexical index is complete; embeddings can be rebuilt later
            if ctx:
                ctx.log(f"Embedding failed for {doc['filename']} (lexical index OK): {e}")
    if ctx:
        ctx.log(f"Indexed {doc['filename']}: {n} pages, {len(chunk_rows)} chunks, labels={label_mode}, "
                f"quality={quality}, status={status}")


def run_scan(ctx: JobContext, folder_ids: list[int] | None = None, force_reindex: bool = False) -> None:
    ctx.update(force=True, phase="starting", indexed=0, failed=0)
    ids = reconcile(ctx, folder_ids, force_reindex)
    ctx.update(force=True, phase="indexing", to_index=len(ids), indexed=0)
    for k, doc_id in enumerate(ids, 1):
        if ctx.cancelled():
            raise InterruptedError("cancelled")
        with session() as c:
            r = c.execute("SELECT filename FROM documents WHERE id=?", (doc_id,)).fetchone()
        ctx.update(current=r["filename"] if r else str(doc_id), doc_no=k, page=0, pages=0)
        index_document(doc_id, ctx)
        ctx.update(indexed=k)
    ctx.log(f"Scan complete: {len(ids)} documents (re)indexed.")


def reindex_documents(ctx: JobContext, doc_ids: list[int]) -> None:
    ctx.update(force=True, phase="indexing", to_index=len(doc_ids), indexed=0)
    for k, doc_id in enumerate(doc_ids, 1):
        index_document(doc_id, ctx)
        ctx.update(indexed=k)
