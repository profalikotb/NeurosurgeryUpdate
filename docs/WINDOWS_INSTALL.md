# Windows installation

Tested target: Windows 10/11, 64-bit. About 10 minutes plus the first library scan.

## 1. Prerequisites

| Tool | Install | Notes |
|---|---|---|
| Python 3.11–3.13 | <https://www.python.org/downloads/> | Tick **Add python.exe to PATH** and keep the **py launcher** |
| Node.js 20 LTS+ | <https://nodejs.org/> | |
| Git | <https://git-scm.com/download/win> | |
| Tesseract OCR (recommended) | `winget install --id UB-Mannheim.TesseractOCR` | Needed for scanned books. For Arabic OCR tick the Arabic language during setup and set `ACADEMY_OCR_LANGUAGE=eng+ara` |
| Ollama (optional) | <https://ollama.com/download> then `ollama pull nomic-embed-text` | Only for semantic search |

Enable long paths once (Telegram folders often exceed 260 characters). The backend also handles them itself,
but other tools benefit. In an **administrator** PowerShell:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
```

## 2. Install

```powershell
cd D:\
git clone <your-private-repo-url> neurosurgery-ai-academy
cd neurosurgery-ai-academy
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The installer creates `backend\.venv`, installs dependencies, generates a random API token into
`backend\.env` and `frontend\.env.local` (UTF-8 without BOM), and builds the frontend.

## 3. Run

```powershell
scripts\start.bat
```

Two console windows open (backend on 127.0.0.1:8000, frontend on localhost:3000) and the browser opens.
Close both windows to stop. To start automatically at logon, put a shortcut to `scripts\start.bat` in
`shell:startup`.

## 4. Index your books

1. **My Neurosurgery Library → Add folder**: `D:\Telegram books` (or **Browse**).
2. **Scan all folders**. Progress, current file and errors appear live; you can keep searching while it runs.
3. Review **Quality report**, then verify bibliographic details of your core textbooks.

Command-line equivalents (useful over Remote Desktop):

```powershell
cd backend
.venv\Scripts\python.exe -m app.cli add-folder "D:\Telegram books"
.venv\Scripts\python.exe -m app.cli scan
.venv\Scripts\python.exe -m app.cli search "far lateral approach vertebral artery"
```

### Nightly incremental scan

```powershell
schtasks /Create /SC DAILY /ST 03:00 /TN "Academy library scan" /TR "\"D:\neurosurgery-ai-academy\scripts\scheduled-scan.bat\""
```

A cross-process lock prevents the scheduled scan and a UI scan from running at the same time.

## 5. Where things are stored

| What | Where | Back up? |
|---|---|---|
| Your books | Unchanged, wherever they are | Your own backups |
| Index, extracted text, metadata you verified | `backend\data\academy.sqlite3` (move with `ACADEMY_DATA_DIR`) | **Yes**: your metadata verification lives here |
| Vector index (semantic, optional) | `backend\data\qdrant` | Rebuildable |
| Scheduled-scan log | `backend\data\scheduled-scan.log` | No |

Index size is roughly 1–1.5× the plain-text size of the books (a 1,500-page textbook ≈ 6–10 MB).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Backend unreachable" in the UI | Backend window closed or crashed. Rerun `scripts\start-backend.bat` and read the error |
| `401 invalid or missing API token` | Tokens in `backend\.env` and `frontend\.env.local` differ. Make them identical and restart both |
| Folder shows **Not reachable** | Drive unplugged / network share offline. Its books are **not** marked missing; they return on the next scan |
| Book stuck at **Needs OCR** | Tesseract not found. Install it, or set `ACADEMY_TESSDATA_PREFIX=C:\Program Files\Tesseract-OCR\tessdata`, then **Re-index** |
| **Error: password protected** | Remove the PDF password with the publisher's tool; the app never cracks protection |
| Port 3000/8000 in use | Edit the port in `start-frontend.bat` / `start-backend.bat` and `BACKEND_URL` |
| Antivirus slows the first scan | Exclude `backend\data` from real-time scanning (not the books folder) |
