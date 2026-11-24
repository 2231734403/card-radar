# Card Radar one-click setup script (ASCII-only for clean Windows PowerShell execution)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host '=== Card Radar v2 One-Click Setup ==='

# 1. Check Python 3.10+
$pyOk = $false
try {
    $ver = (& py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
    if ($ver) {
        $parts = $ver.Split('.')
        if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
            Write-Host "[OK] Python $ver detected"
            $pyOk = $true
        }
    }
} catch {}
if (-not $pyOk) {
    Write-Host '[ERR] Python 3.10+ is required. Install from https://www.python.org/downloads/ and re-run.'
    exit 1
}

# 2. Check / install Pillow
$hasPil = $false
try {
    & py -3 -c "import PIL" 2>$null
    if ($LASTEXITCODE -eq 0) { $hasPil = $true }
} catch {}
if ($hasPil) {
    Write-Host '[OK] Pillow already installed'
} else {
    Write-Host '[INFO] Installing Pillow (--user)...'
    & py -3 -m pip install --user pillow
}

# 3. Check optional AI engine
if (Test-Path (Join-Path $root 'ai_engine\realesrgan-ncnn-vulkan.exe')) {
    Write-Host '[OK] Real-ESRGAN AI engine detected (ai_engine/)'
} else {
    Write-Host '[INFO] Real-ESRGAN not found in ai_engine/ (Pillow progressive upscaler will be used as fallback)'
}

# 4. Register scheduled tasks + startup channel
Write-Host '[INFO] Registering biweekly tasks and logon auto-start...'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\install_tasks.ps1')
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\install_server_task.ps1')
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\install_startup_channel.ps1')

# 5. Start server and verify health
Write-Host '[INFO] Starting Card Radar local server...'
& cmd /c (Join-Path $root 'scripts\run_server.cmd')
Start-Sleep -Seconds 2
try {
    $h = Invoke-RestMethod 'http://127.0.0.1:8819/api/v2/health' -TimeoutSec 5
    Write-Host "[OK] Server online: v$($h.version) | totalCards=$($h.totalCards) | aiEngine=$($h.aiEngine)"
    Start-Process 'http://127.0.0.1:8819/'
} catch {
    Write-Host "[WARN] Server did not respond yet: $($_.Exception.Message)"
}
