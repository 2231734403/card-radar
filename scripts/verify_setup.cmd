@echo off
rem Self-healing check for Card Radar v2 (pure ASCII).
cd /d "%~dp0.."
echo [1/4] Checking and registering scheduled tasks (idempotent)...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_tasks.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_server_task.ps1
echo [2/4] Ensuring Startup-folder auto-start shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_startup_channel.ps1
echo [3/4] Ensuring local server is running (hidden window)...
call scripts\run_server.cmd
echo [4/4] Health verification:
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "try { $r = Invoke-RestMethod 'http://127.0.0.1:8819/api/v2/health' -TimeoutSec 4; Write-Host ('[OK] Card Radar v' + $r.version + ' listening (PID ' + $r.pid + ', totalCards=' + $r.totalCards + ')') } catch { Write-Host '[WARN] Server health check failed - check data\logs' }"
for %%T in (PjskCardWikiServer PjskCardWikiWeeklyScrape BandoriCardWikiWeeklyScrape ShinyColorsCardWikiScrape OnotesCardWikiScrape) do (
  schtasks /Query /TN "%%T" >nul 2>&1 && echo [OK] task %%T || echo [WARN] task %%T missing
)
pause
