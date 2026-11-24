@echo off
rem Our Notes biweekly scrape entry (pure ASCII).
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
py -X utf8 scraper\onotes_scrape.py >> data\logs\runner.log 2>&1
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -File scripts\popup_fail.ps1 -Module "Our Notes" -LogFile "onotes_scrape.log" -RetryCmd "scripts\run_onotes_scrape.cmd"
exit /b 0
