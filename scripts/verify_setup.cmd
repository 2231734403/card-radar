@echo off
rem Self-healing check: re-register everything if missing, start the
rem server if not running, then report status. Run this any time the
rem site "cannot be opened" - it fixes all known failure modes.
cd /d "%~dp0.."
echo [1/4] Re-registering scheduled tasks (idempotent)...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_tasks.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_server_task.ps1
echo [2/4] Ensuring Startup-folder auto-start channel...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_startup_channel.ps1
echo [3/4] Ensuring server is running (hidden window)...
call scripts\run_server.cmd
echo [4/4] Status:
timeout /t 3 /nobreak >nul
netstat -ano | findstr "LISTENING" | findstr ":8819 " >nul 2>&1
if %errorlevel%==0 (echo [OK] server listening on http://127.0.0.1:8819) else (echo [WARN] server not listening yet - check data\logs\server.log)
schtasks /Query /TN "PjskCardWikiWeeklyScrape" >nul 2>&1 && echo [OK] weekly scrape task exists || echo [WARN] weekly scrape task missing
schtasks /Query /TN "PjskCardWikiServer" >nul 2>&1 && echo [OK] logon server task exists || echo [WARN] logon server task missing
pause
