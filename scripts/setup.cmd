@echo off
rem Card Radar one-click bootstrap installer (pure ASCII).
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
pause
