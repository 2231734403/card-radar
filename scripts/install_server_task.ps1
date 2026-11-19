# Register the site server logon task. The action goes through wscript.exe
# + autostart_hidden.vbs (hidden wrapper), so NO console window ever
# flashes at logon. Fallback if the logon trigger is denied: daily 00:05
# keep-alive (run_server.cmd is idempotent). Keep this file ASCII-only.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$scripts = Join-Path $root 'scripts'

$serverAction = New-ScheduledTaskAction -Execute 'wscript.exe' `
    -Argument ('//nologo "' + (Join-Path $scripts 'autostart_hidden.vbs') + '"')
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

$user = "$env:USERDOMAIN\$env:USERNAME"
if (Get-ScheduledTask -TaskName 'PjskCardWikiServer' -ErrorAction SilentlyContinue) {
    # Idempotent self-heal: never overwrite an existing task (Register -Force
    # is access-denied for tasks created elevated, and would clobber tweaks).
    Write-Host '[SKIP] PjskCardWikiServer  already exists'
    exit 0
}
try {
    $serverTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    Register-ScheduledTask -TaskName 'PjskCardWikiServer' `
        -Action $serverAction -Trigger $serverTrigger -Settings $settings -User $user `
        -Description 'Pjsk radar: start local site (127.0.0.1:8819) at logon (hidden window)' -Force | Out-Null
    Write-Host '[OK] PjskCardWikiServer  logon auto-start (hidden)'
} catch {
    Write-Host "[WARN] logon trigger denied: $($_.Exception.Message)"
    $serverTrigger = New-ScheduledTaskTrigger -Daily -At 00:05
    Register-ScheduledTask -TaskName 'PjskCardWikiServer' `
        -Action $serverAction -Trigger $serverTrigger -Settings $settings -User $user `
        -Description 'Pjsk radar: keep local site alive (127.0.0.1:8819) (hidden window)' -Force | Out-Null
    Write-Host '[OK] PjskCardWikiServer  daily 00:05 keep-alive (run_server.cmd is idempotent, hidden)'
}
