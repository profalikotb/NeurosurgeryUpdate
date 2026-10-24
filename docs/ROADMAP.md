# Roadmap

Each phase ships as a working, tested system with Windows instructions. Later phases depend on the
citation integrity contract in [ARCHITECTURE.md](ARCHITECTURE.md).

| Phase | Scope | Key design decisions |
|---|---|---|
| **1 ✅ Local Reference Library** | Folder scan, incremental/dedupe, OCR, page labels, chapters, hybrid search, citation build/verify, viewer, quality report, EN/AR UI | SQLite FTS5 as the always-available core; vectors optional |
| **2 AI Teaching Assistant** | Grounded chat (Quick Recall / Structured / Professor-level), answer modes (My Books Only…), MCQ generator with exam mode, short-essay + marking scheme, viva examiner with rubric | Provider abstraction (Ollama, Anthropic, OpenAI-compatible); retrieve → constrained generation with chunk ids → server-side citation build → quote verification; explicit consent before any excerpt goes to a cloud model; MCQ answer consistency check (model must re-derive the key from the cited passage) |
| **3 Surgical Decision Education** | "Which surgical approach and why?", structured case discussion | Missing-information checklist first; approach comparison table; never a single "correct" approach; evidence strength per row |
| **4 Recent Evidence** | PubMed E-utilities / PMC OA / Crossref surveillance, date windows, 18-question appraisal, evidence categories, "What has changed since my textbook?", Egyptian practice context | Reproducible rule-based evidence categorisation (design, sample, consistency) rather than opaque scores; DOI/PMID dedupe; retraction checks via Crossref; search-run log shown with every update |
| **5 Academic Teaching Studio** | Lecture builder, "Teach this to my residents", PPTX/PDF/DOCX export, collections, flashcards with spaced repetition, question bank, mistake tracking | Exports carry references and source attributions; A4 print layouts |
| **6 Security & Deployment** | Accounts, roles, audit UI, de-identification guard for patient input, encryption at rest for clinical content, deletion workflows, secure remote access (Tailscale/Cloudflare Access), Vercel frontend option | Default stays local-only; remote access opt-in |

## Benchmarks (start of Phase 2)

A benchmark file of 30–50 questions, each with a manually verified book/page answer from your library, will be
added under `backend/tests/benchmark/`. Retrieval recall@10 and citation-verification pass rate are tested
against the source text, not judged by another model.
