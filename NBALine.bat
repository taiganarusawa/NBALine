@echo off
rem Double-click to start NBALine. Close this window to stop it.
cd /d "%~dp0"
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5055"
rem After NBALine's code changes, the page's "Restart now" button stops the server with exit code 3,
rem and this loop starts it again with the new code (the window stays open).
set NBALINE_RESTARTABLE=1
:run
.venv\Scripts\python.exe webapp.py
if %errorlevel% equ 3 goto run
