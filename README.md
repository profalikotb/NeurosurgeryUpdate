# Prof. Ali Kotb Neurosurgery AI Academy

**Evidence-Based Neurosurgery | Clinical Decision Support | Surgical Education | Research Updates**

A private, bilingual (English / العربية) neurosurgical knowledge platform that indexes your own textbook
collection in place and makes every answer traceable to a real page.

> **Status: Phase 1 — Local Reference Library (working, tested).**
> Phases 2–6 (grounded AI chat, MCQ/essay/viva, surgical approaches, PubMed surveillance, teaching studio,
> accounts) build on the retrieval and citation layer delivered here. See [docs/ROADMAP.md](docs/ROADMAP.md).

## What Phase 1 does

| Capability | Detail |
|---|---|
| Folder indexing | Add any number of Windows folders (e.g. `D:\Telegram books`); recursive scan; books stay where they are, opened read-only |
| Formats | PDF, EPUB, MOBI, FB2 (page-accurate or reflowable), DOCX, TXT/MD |
| Incremental | New / changed / moved / deleted files detected (size+mtime, then SHA-256); unchanged books are skipped |
| Duplicates | Exact copies (hash) are linked, never indexed twice; same title+edition+length flagged as *possible* duplicate |
| Printed page numbers | Embedded PDF page labels → else inferred from running headers/footers (flagged *inferred*) → else "PDF p. N" stated explicitly |
| Chapters | From the embedded table of contents; book-wrapper top levels are skipped automatically |
| OCR | Tesseract on image-only pages; OCR text is flagged in every citation; books needing OCR are reported |
| Search | SQLite FTS5 / BM25 with ~80 neurosurgical synonym groups (acoustic neuroma ↔ vestibular schwannoma, PICA, ACDF, EVD…); optional local semantic search (Ollama + Qdrant) fused by reciprocal-rank fusion |
| Citations | Built only from stored facts; each field carries provenance (PDF metadata / title pages / file name / you) |
| Verification | `POST /api/citations/verify` checks a quote against the cited page (exact or fuzzy), detects off-by-one pages, refuses unindexed books |
| Viewer | Page image with highlighted terms, extracted text, jump to printed page, open original PDF at the page |
| Quality report | Text coverage, OCR status, page-label mode, TOC presence, errors — per book |
| Privacy | Everything local. No book text leaves the machine in Phase 1. API bound to 127.0.0.1 with a server-side token |

## Quick start (Windows)

```powershell
git clone <your-private-repo-url> neurosurgery-ai-academy
cd neurosurgery-ai-academy
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
scripts\start.bat
```

Then open <http://localhost:3000> → **My Neurosurgery Library** → **Add folder** (type the path or use **Browse**)
→ **Scan all folders**. Full instructions: [docs/WINDOWS_INSTALL.md](docs/WINDOWS_INSTALL.md).

To try it before pointing it at real books:

```powershell
backend\.venv\Scripts\python.exe scripts\make_sample_library.py D:\AcademySample
```

…and add `D:\AcademySample` as a folder. The sample is original demonstration text, not clinical reference material.

## Adding your real textbooks

1. Add each top-level folder once (`D:\Telegram books` already covers `Telegram Desktop` and `Notebooklm books` beneath it).
2. Scan. Large libraries take a while on the first pass: text PDFs index at roughly 1,000–3,000 pages/minute; OCR runs at ~2–6 s/page.
3. Open **Quality report**. Fix in this order: *Error* (corrupt/password-protected) → *Needs OCR* (install Tesseract, rescan) → *Partial text*.
4. Open each important book and **verify its bibliographic details** (title, authors, edition, year). Citations from
   unverified books are labelled *metadata not yet verified*; Phase 2 answers can be restricted to verified books.
5. Spot-check one citation in any book whose page numbers are marked *inferred*.
6. Optional: schedule `scripts\scheduled-scan.bat` daily in Task Scheduler so newly downloaded books are indexed automatically.

## Easiest: one-click cloud (recommended for phone use)

`render.yaml` + `Dockerfile` deploy the whole app as one password-protected website on Render. Books are
uploaded from the phone (the iPhone picker reads Google Drive directly). Three steps: [SETUP-CLOUD.md](SETUP-CLOUD.md).

## Cloud mode: books from Google Drive, no PC

Optional add-on to the one-click cloud: the server reads a shared Google Drive folder (read-only) and indexes
new books placed there automatically. Step by step: [docs/CLOUD_DRIVE.md](docs/CLOUD_DRIVE.md).

## Remote access via Vercel

Deploy **only `frontend/`** (Root Directory = `frontend`); the backend stays on the PC and is reached through a
tunnel (Tailscale Funnel or Cloudflare). A UI password is mandatory on Vercel. Step-by-step: [docs/VERCEL.md](docs/VERCEL.md).

## Docker (alternative)

```bash
cp backend/.env.docker.example backend/.env.docker   # set the same random token in both files
cp frontend/.env.docker.example frontend/.env.docker
docker compose up -d --build
```

Books are mounted read-only (edit the volume line in `docker-compose.yml`); inside the app add them by container path, e.g. `/books/telegram`.

## Repository layout

```
backend/   FastAPI service: indexing, search, citations, page rendering   (pytest suite in backend/tests)
frontend/  Next.js 15 + TypeScript + Tailwind, EN/AR with RTL, server-side API proxy
scripts/   Windows install/start/scheduled-scan, sample library generator
docs/      Windows install, architecture, roadmap
```

## Security and copyright

- Book files, extracted text, indexes and `.env` files are git-ignored; CI fails if a PDF/EPUB/database is committed. Keep the repository **private**.
- The browser never receives the API token — Next.js injects it server-side (`/api/backend/*`).
- Before exposing the UI beyond localhost, set `ACADEMY_UI_PASSWORD` (HTTP Basic auth) and use HTTPS/VPN (e.g. Tailscale). Full accounts and roles arrive in Phase 6.
- Generated answers (Phase 2+) quote short supporting passages only; chapters are never reproduced.

## Development

```bash
cd backend && pip install -r requirements-dev.txt -r requirements-semantic.txt && pytest -q && ruff check app tests
cd frontend && npm ci && npm run typecheck && npm run lint && npm run build
```

API documentation: <http://127.0.0.1:8000/docs> (pass the token as header `X-Academy-Token`).
