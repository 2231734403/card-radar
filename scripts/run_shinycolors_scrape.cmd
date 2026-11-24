@echo off
rem ShinyColors biweekly scrape entry (pure ASCII).
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
py -X utf8 scraper\shinycolors_scrape.py >> data\logs\runner.log 2>&1
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -File scripts\popup_fail.ps1 -Module "ShinyColors" -LogFile "shinycolors_scrape.log" -RetryCmd "scripts\run_shinycolors_scrape.cmd"
exit /b 0
