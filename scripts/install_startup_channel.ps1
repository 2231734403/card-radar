# Ensure the Startup-folder second channel shortcut points to the
# windowless wscript wrapper (PjskCardWikiServer.lnk -> autostart_hidden.vbs).
# This file was MISSING before 2026-11-14 (verify_setup.cmd step 2 silently
# failed); the shortcut used to be a bare .cmd that flashed a console.
# Keep this file ASCII-only.
$ErrorActionPreference = 'Stop'
$ws = New-Object -ComObject WScript.Shell
$startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$root = Split-Path -Parent $PSScriptRoot
$vbs = Join-Path $root 'scripts\autostart_hidden.vbs'
$lnk = $ws.CreateShortcut((Join-Path $startup 'PjskCardWikiServer.lnk'))
$lnk.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$lnk.Arguments = '//nologo "' + $vbs + '"'
$lnk.WorkingDirectory = $root
$lnk.WindowStyle = 1
$lnk.Save()
Write-Host '[OK] startup shortcut -> wscript autostart_hidden.vbs'
