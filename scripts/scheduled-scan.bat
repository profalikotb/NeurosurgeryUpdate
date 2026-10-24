@echo off
REM Unattended incremental scan, for Windows Task Scheduler (e.g. daily at 03:00).
REM Only new/changed/deleted files are processed. Do not run while the UI is scanning.
REM   schtasks /Create /SC DAILY /ST 03:00 /TN "Academy library scan" /TR "\"%CD%\scripts\scheduled-scan.bat\""
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" -m app.cli scan >> "data\scheduled-scan.log" 2>&1
