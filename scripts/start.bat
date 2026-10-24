@echo off
REM Starts backend (127.0.0.1:8000) and frontend (http://localhost:3000) in two windows, then opens the browser.
setlocal
set ROOT=%~dp0..
start "Academy backend" cmd /k call "%ROOT%\scripts\start-backend.bat"
timeout /t 3 /nobreak >nul
start "Academy frontend" cmd /k call "%ROOT%\scripts\start-frontend.bat"
timeout /t 5 /nobreak >nul
start "" http://localhost:3000
endlocal
