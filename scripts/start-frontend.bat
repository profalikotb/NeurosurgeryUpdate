@echo off
cd /d "%~dp0..\frontend"
set NEXT_TELEMETRY_DISABLED=1
if not exist ".next\BUILD_ID" call npm run build
call npm start
