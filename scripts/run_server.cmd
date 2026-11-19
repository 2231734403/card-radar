@echo off
rem Pjsk radar: start the local site server. Idempotent: exits when
rem port 8819 is already LISTENING. The server is spawned with a hidden
rem window (run_server_hidden.vbs) so nobody can close it by accident.
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
netstat -ano | findstr "LISTENING" | findstr ":8819 " >nul 2>&1
if %errorlevel%==0 exit /b 0
wscript //nologo "%~dp0run_server_hidden.vbs"
exit /b 0
