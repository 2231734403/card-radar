@echo off
rem Onotes (Our Notes) biweekly scrape entry: run the incremental scraper; popup on failure.
rem (All .cmd files in this project are pure ASCII on purpose - UTF-8
rem  Chinese comments get mangled by cmd's GBK parsing, tieba-radar E09.)
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
py -X utf8 scraper\onotes_scrape.py >> data\logs\runner.log 2>&1
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -File scripts\popup_fail.ps1
exit /b 0
