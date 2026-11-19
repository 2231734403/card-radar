# Register the card-radar scheduled tasks. All actions go through wscript.exe
# + a hidden VBS wrapper, so NO console window ever flashes for the user.
#   1) PjskCardWikiWeeklyScrape    - BIWEEKLY Mon 09:00 incremental scrape
#      (StartWhenAvailable: runs after boot if the slot was missed)
#   2) PjskCardWikiServer          - local site server at logon
#   3) BandoriCardWikiWeeklyScrape - BIWEEKLY Mon 09:20 incremental scrape
#   4) ShinyColorsCardWikiScrape   - BIWEEKLY Mon 09:40 incremental scrape
#   5) OnotesCardWikiScrape        - BIWEEKLY Mon 10:00 incremental scrape
# Keep this file ASCII-only (see HANDOFF section 7).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$scripts = Join-Path $root 'scripts'

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

# 1. Biweekly scrape task (hidden wrapper: run_scrape_hidden.vbs)
# Idempotent self-heal: register only when MISSING; never overwrite an
# existing task (Register -Force is access-denied for tasks created
# elevated, and would clobber manual tweaks anyway).
if (Get-ScheduledTask -TaskName 'PjskCardWikiWeeklyScrape' -ErrorAction SilentlyContinue) {
    Write-Host '[SKIP] PjskCardWikiWeeklyScrape  already exists'
} else {
    $scrapeAction = New-ScheduledTaskAction -Execute 'wscript.exe' `
        -Argument ('//nologo "' + (Join-Path $scripts 'run_scrape_hidden.vbs') + '"')
    $scrapeTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 09:00 -WeeksInterval 2
    Register-ScheduledTask -TaskName 'PjskCardWikiWeeklyScrape' `
        -Action $scrapeAction -Trigger $scrapeTrigger -Settings $settings `
        -Description 'Pjsk radar: biweekly incremental scrape of pjsk.moe card data (hidden window)' -Force | Out-Null
    Write-Host '[OK] PjskCardWikiWeeklyScrape  biweekly Mon 09:00 (hidden)'
}

# 2. Site server task at logon (hidden wrapper: autostart_hidden.vbs)
if (Get-ScheduledTask -TaskName 'PjskCardWikiServer' -ErrorAction SilentlyContinue) {
    Write-Host '[SKIP] PjskCardWikiServer  already exists'
} else {
    $serverAction = New-ScheduledTaskAction -Execute 'wscript.exe' `
        -Argument ('//nologo "' + (Join-Path $scripts 'autostart_hidden.vbs') + '"')
    $serverTrigger = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask -TaskName 'PjskCardWikiServer' `
        -Action $serverAction -Trigger $serverTrigger -Settings $settings `
        -Description 'Pjsk radar: start local site (127.0.0.1:8819) at logon (hidden window)' -Force | Out-Null
    Write-Host '[OK] PjskCardWikiServer  logon auto-start (hidden)'
}

# 3. Bandori biweekly scrape task (hidden wrapper: run_bandori_hidden.vbs)
# 09:20, staggered after the pjsk 09:00 slot so the two scrapers never
# compete for bandwidth. Same idempotent SKIP-if-exists semantics.
if (Get-ScheduledTask -TaskName 'BandoriCardWikiWeeklyScrape' -ErrorAction SilentlyContinue) {
    Write-Host '[SKIP] BandoriCardWikiWeeklyScrape  already exists'
} else {
    $bandoriAction = New-ScheduledTaskAction -Execute 'wscript.exe' `
        -Argument ('//nologo "' + (Join-Path $scripts 'run_bandori_hidden.vbs') + '"')
    $bandoriTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 09:20 -WeeksInterval 2
    Register-ScheduledTask -TaskName 'BandoriCardWikiWeeklyScrape' `
        -Action $bandoriAction -Trigger $bandoriTrigger -Settings $settings `
        -Description 'Bandori radar: biweekly incremental scrape of bestdori card data (hidden window)' -Force | Out-Null
    Write-Host '[OK] BandoriCardWikiWeeklyScrape  biweekly Mon 09:20 (hidden)'
}

# 4. ShinyColors biweekly scrape task (hidden wrapper: run_shiny_hidden.vbs)
# 09:40, staggered after bandori. Same idempotent SKIP-if-exists semantics.
if (Get-ScheduledTask -TaskName 'ShinyColorsCardWikiScrape' -ErrorAction SilentlyContinue) {
    Write-Host '[SKIP] ShinyColorsCardWikiScrape  already exists'
} else {
    $shinyAction = New-ScheduledTaskAction -Execute 'wscript.exe' `
        -Argument ('//nologo "' + (Join-Path $scripts 'run_shiny_hidden.vbs') + '"')
    $shinyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 09:40 -WeeksInterval 2
    Register-ScheduledTask -TaskName 'ShinyColorsCardWikiScrape' `
        -Action $shinyAction -Trigger $shinyTrigger -Settings $settings `
        -Description 'ShinyColors radar: biweekly incremental scrape of shinycolors.moe card data (hidden window)' -Force | Out-Null
    Write-Host '[OK] ShinyColorsCardWikiScrape  biweekly Mon 09:40 (hidden)'
}

# 5. Onotes (Our Notes) biweekly scrape task (hidden wrapper: run_onotes_hidden.vbs)
# 10:00, staggered after shiny. Same idempotent SKIP-if-exists semantics.
if (Get-ScheduledTask -TaskName 'OnotesCardWikiScrape' -ErrorAction SilentlyContinue) {
    Write-Host '[SKIP] OnotesCardWikiScrape  already exists'
} else {
    $onotesAction = New-ScheduledTaskAction -Execute 'wscript.exe' `
        -Argument ('//nologo "' + (Join-Path $scripts 'run_onotes_hidden.vbs') + '"')
    $onotesTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 10:00 -WeeksInterval 2
    Register-ScheduledTask -TaskName 'OnotesCardWikiScrape' `
        -Action $onotesAction -Trigger $onotesTrigger -Settings $settings `
        -Description 'Onotes radar: biweekly incremental scrape of bdon.moe card data (hidden window)' -Force | Out-Null
    Write-Host '[OK] OnotesCardWikiScrape  biweekly Mon 10:00 (hidden)'
}
