# Prof. Ali Kotb Neurosurgery AI Academy - Windows installer (Phase 1)
# Run from the repository root in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Missing: $cmd. $hint" -ForegroundColor Red
        exit 1
    }
}
# .env files must be UTF-8 WITHOUT BOM (PowerShell 5's Set-Content -Encoding UTF8 writes a BOM,
# which silently corrupts the first variable name).
function Write-Utf8NoBom($path, $text) {
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

Need "py" "Install Python 3.11+ from https://www.python.org/downloads/ (tick 'Add to PATH' and the 'py launcher')."
Need "node" "Install Node.js 20 LTS or newer from https://nodejs.org/"
$pyver = & py -3 -c "import sys;print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
if ([version]$pyver -lt [version]"3.11") { Write-Host "Python $pyver found; 3.11+ required." -ForegroundColor Red; exit 1 }
$nodever = (& node -v).TrimStart("v")
if ([version]$nodever -lt [version]"20.0") { Write-Host "Node $nodever found; 20+ required." -ForegroundColor Red; exit 1 }

Write-Host "`n[1/4] Backend virtual environment" -ForegroundColor Cyan
if (-not (Test-Path "backend\.venv")) { & py -3 -m venv backend\.venv }
& backend\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -q
$sem = Read-Host "Install optional semantic search (needs Ollama later)? [y/N]"
if ($sem -match "^[yY]") { & backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-semantic.txt -q }

Write-Host "[2/4] Secrets and configuration" -ForegroundColor Cyan
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$token = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
if (-not (Test-Path "backend\.env")) {
    $tess = ""
    $tessDir = "C:\Program Files\Tesseract-OCR"
    if (Test-Path "$tessDir\tessdata") { $tess = "ACADEMY_TESSDATA_PREFIX=$tessDir\tessdata`r`n" }
    Write-Utf8NoBom "$Root\backend\.env" @"
ACADEMY_API_TOKEN=$token
ACADEMY_DATA_DIR=$Root\backend\data
ACADEMY_OCR_ENABLED=true
ACADEMY_OCR_LANGUAGE=eng
$tess# ACADEMY_SEMANTIC_ENABLED=true
# ACADEMY_EMBEDDING_MODEL=nomic-embed-text
"@
    Write-Utf8NoBom "$Root\frontend\.env.local" @"
BACKEND_URL=http://127.0.0.1:8000
ACADEMY_API_TOKEN=$token
# ACADEMY_UI_USER=prof
# ACADEMY_UI_PASSWORD=set-this-before-exposing-beyond-localhost
"@
    Write-Host "  Generated a new API token in backend\.env and frontend\.env.local"
} else {
    Write-Host "  backend\.env exists - kept unchanged"
}

Write-Host "[3/4] Frontend build" -ForegroundColor Cyan
Push-Location frontend
& npm ci --no-audit --no-fund
$env:NEXT_TELEMETRY_DISABLED = "1"
& npm run build
Pop-Location

Write-Host "[4/4] Checks" -ForegroundColor Cyan
if (-not (Get-Command tesseract -ErrorAction SilentlyContinue) -and -not (Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe")) {
    Write-Host "  Tesseract OCR not found: scanned books will be flagged 'Needs OCR'." -ForegroundColor Yellow
    Write-Host "  Install with:  winget install --id UB-Mannheim.TesseractOCR   then re-run this script." -ForegroundColor Yellow
}
Write-Host "`nDone. Start the academy with:  scripts\start.bat" -ForegroundColor Green
