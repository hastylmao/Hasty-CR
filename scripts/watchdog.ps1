# Restart the HastyCR supervisor if it has died or wedged.
#
# Registered as a Scheduled Task that fires every five minutes. It is the outer
# ring of the safety net: the supervisor restarts the bot, and this restarts the
# supervisor. It deliberately does nothing clever - the only judgement it makes
# is "is the heartbeat fresh", because a watchdog that can itself fail in an
# interesting way is not a watchdog.

$ErrorActionPreference = 'SilentlyContinue'
$root = 'C:\Users\aksha\Downloads\HastyCR'
$python = Join-Path $root '.venvs\buildabot\Scripts\python.exe'
$state = Join-Path $root 'tmp\live\supervisor_state.json'
$logFile = Join-Path $root 'tmp\live\watchdog.log'
$staleMinutes = 20

function Write-Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" | Out-File -Append -Encoding utf8 $logFile
}

$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*scripts\supervisor.py*' }

$fresh = $false
if (Test-Path $state) {
    try {
        $epoch = (Get-Content $state -Raw | ConvertFrom-Json).heartbeat_epoch
        $age = ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $epoch) / 60.0
        $fresh = $age -lt $staleMinutes
        if (-not $fresh) { Write-Log "heartbeat stale: $([math]::Round($age,1)) min" }
    } catch { Write-Log "state unreadable: $($_.Exception.Message)" }
}

if ($running -and $fresh) { exit 0 }

if ($running -and -not $fresh) {
    Write-Log "supervisor wedged (pid $($running.ProcessId)); restarting"
    foreach ($p in $running) { Stop-Process -Id $p.ProcessId -Force }
    # A wedged supervisor usually means a wedged bot underneath it.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*scripts\cr_bot.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-Sleep -Seconds 3
}

if (-not $running) { Write-Log 'supervisor not running; starting' }

# No stdout redirect: supervisor.py writes its own log, and a fixed redirect
# target would be locked by the previous instance on the next restart.
Start-Process -FilePath $python `
    -ArgumentList 'scripts\supervisor.py' `
    -WorkingDirectory $root `
    -WindowStyle Hidden
Write-Log 'supervisor started'
