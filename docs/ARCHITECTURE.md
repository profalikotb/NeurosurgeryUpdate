# Architecture

```
Browser (EN/AR, RTL) ──► Next.js server ──(X-Academy-Token, server-side only)──► FastAPI 127.0.0.1:8000
                          /api/backend/*                                           │
                          optional Basic auth                                      ├─ SQLite (WAL): folders, documents,
                                                                                   │   pages, toc, chunks, FTS5, jobs, audit
                                                                                   ├─ Qdrant embedded (optional vectors)
                                                                                   ├─ Ollama (optional local embeddings)
                                                                                   └─ Books on disk (read-only)
```

## Indexing pipeline

1. **Discover**: `os.walk` over enabled, reachable folders; supported extensions only; temp/hidden/system folders skipped.
2. **Reconcile**: unchanged (path+size+mtime) → skip. Otherwise SHA-256 →
   *restored* (same hash, previously missing) · *changed* (re-index) · *moved* (hash matches a vanished
   document → path updated, no re-extraction) · *duplicate* (hash matches a present document → linked, not indexed) · *new*.
   Documents that vanished from **reachable** folders become *missing* and leave the search index; a duplicate of
   a missing original is promoted automatically. Unreachable folders never cause deletions.
3. **Extract** (PyMuPDF): per-page text with dehyphenation; image-only pages → Tesseract OCR within a per-book
   budget; embedded page labels; embedded TOC; embedded metadata. DOCX/TXT become numbered sections.
4. **Resolve printed pages**: embedded labels; else windowed offset voting from header/footer numbers (needs ≥3
   agreeing neighbouring pages); else none. Source is stored per page.
5. **Clean**: running headers/footers and bare page numbers are removed *after* page resolution.
6. **Chunk**: ~1,400 characters on paragraph/sentence boundaries, **never across pages** — every hit maps to exactly one page.
7. **Metadata**: title/authors/edition/year/publisher/ISBN only when literally present (PDF metadata, title pages,
   file name); ISBN checksums validated; provenance stored; user-entered values are never overwritten.
8. **Quality score** (0–100): text coverage, page-label mode, TOC, OCR share, with human-readable notes.

`EXTRACTOR_VERSION` bumps trigger automatic re-extraction of existing books on the next scan.

## Retrieval

- FTS5 (`porter unicode61 remove_diacritics 2`), BM25 weighted text 1.0 / chapter 2.0 / section 1.5.
- Query parsing: quoted phrases, multi-word synonym recognition, stop-word removal; AND first, then OR to fill.
- Very short abbreviations are only searched when typed (prevents "VS" matching "vs." = versus).
- Optional semantic layer: `search_document:`/`search_query:` prefixed embeddings, cosine in Qdrant, fused with
  BM25 by reciprocal-rank fusion (k=60). Failure degrades to lexical with `semantic_error` reported.

## Citation integrity contract (used by every later phase)

1. A claim may cite only a `chunk_id` returned by retrieval in the same request.
2. The citation string is produced by `citations.build()` from stored rows, never by the LLM.
3. Any quotation the model emits is checked with `citations.verify_quote()`; failures are removed or flagged.
4. Documents not in status `indexed|partial|ocr_needed` cannot be cited.
5. Unverified metadata, inferred page numbers and OCR text are always visibly labelled.

## Security model (Phase 1)

- Backend listens on 127.0.0.1; shared token compared in constant time; CORS limited to the frontend origin.
- Files are served only by document id from the database, never by client-supplied path.
- Folder browser lists directories only. All mutating operations are written to `audit_log`.
- Phase 6 adds user accounts, roles, encrypted patient-related storage and remote-access hardening.
