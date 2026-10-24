@echo off
REM Backend API. Bound to 127.0.0.1 only: it is reachable from this computer, not the network.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\backend"
if not exist ".venv\Scripts\python.exe" (
  echo Run scripts\install.ps1 first.
  exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
