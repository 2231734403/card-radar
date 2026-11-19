@echo off
rem Open the local card gallery; makes sure the server is running first.
cd /d "%~dp0"
call scripts\run_server.cmd
start "" http://127.0.0.1:8819/
