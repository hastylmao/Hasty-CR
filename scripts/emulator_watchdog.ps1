# Restart the Clash Royale emulator instance if it dies, and nothing else.
#
# The existing watchdog restarts the supervisor, and the supervisor restarts the
# bot, but nothing restarted the emulator underneath all of it. Over a long
# unattended run that is the gap that ends the run.
#
# THE IMPORTANT PART: this machine runs more than one MuMu instance. Instance 0
# is a separate device belonging to an unrelated Clash of Clans setup, and
# restarting it would kill that run. So this is pinned to instance 3 and refuses
# to act unless the instance still has the name it was identified by.
#
# The identification, recorded so it can be re-checked rather than trusted:
#   - the bot talks to 127.0.0.1:7555
#   - MuMuManager reports instance 3 ("Android Device-1-2") on port 16480
#   - both ports return the same focused window handle, running
#     com.supercell.clashroyale, so they are one device
#
# It is also deliberately slow to act. A single failed adb check is usually a
# transient during an app relaunch, so a restart needs two consecutive failures
# a few minutes apart, tracked through a marker file.

$ErrorActionPreference = 'SilentlyContinue'

$root       = 'C:\Users\aksha\Downloads\HastyCR'
$adb        = 'C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe'
$manager    = 'C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe'
$serial     = '127.0.0.1:7555'
$vmIndex    = 3
$vmName     = 'Android Device-1-2'
$logFile    = Join-Path $root 'tmp\live\emulator_watchdog.log'
$strikeFile = Join-Path $root 'tmp\live\emulator_strike.txt'

function Write-Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" | Out-File -Append -Encoding utf8 $logFile
}

# --- is the device reachable? -------------------------------------------------

$devices = (& $adb devices 2>$null) -join "`n"
if ($devices -match [regex]::Escape($serial) -and $devices -match 'device') {
    if (Test-Path $strikeFile) { Remove-Item $strikeFile -Force }
    exit 0
}

# One reconnect attempt costs nothing and fixes most drops on its own.
& $adb connect $serial | Out-Null
Start-Sleep -Seconds 3
$devices = (& $adb devices 2>$null) -join "`n"
if ($devices -match [regex]::Escape($serial) -and $devices -match 'device') {
    Write-Log 'adb reconnect recovered the device'
    if (Test-Path $strikeFile) { Remove-Item $strikeFile -Force }
    exit 0
}

# --- two strikes before touching the emulator --------------------------------

$strikes = 0
if (Test-Path $strikeFile) { $strikes = [int](Get-Content $strikeFile -Raw).Trim() }
$strikes++
$strikes | Out-File -Encoding utf8 $strikeFile
if ($strikes -lt 2) {
    Write-Log "device unreachable (strike $strikes); waiting for the next check"
    exit 0
}

# --- verify the instance is the one we mean before restarting it -------------

$info = & $manager info -v $vmIndex 2>$null | ConvertFrom-Json
if (-not $info) {
    Write-Log 'MuMuManager returned nothing; not touching any instance'
    exit 1
}
# `info -v <n>` returns the object directly; `-v all` returns a map. Handle both.
if ($info.PSObject.Properties.Name -contains "$vmIndex") { $info = $info."$vmIndex" }

if ($info.name -ne $vmName) {
    Write-Log "REFUSING to restart: instance $vmIndex is named '$($info.name)', expected '$vmName'. Another emulator may be using this index."
    exit 1
}

Write-Log "device unreachable after $strikes checks; restarting instance $vmIndex ('$vmName') only"
& $manager control -v $vmIndex restart | Out-Null

# Booting Android takes a while; the bot's own RECOVER path relaunches Clash
# Royale once the device answers, so this only has to get adb back.
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 10
    & $adb connect $serial | Out-Null
    $devices = (& $adb devices 2>$null) -join "`n"
    if ($devices -match [regex]::Escape($serial) -and $devices -match 'device') {
        Write-Log "device back after $((($i + 1) * 10))s"
        Remove-Item $strikeFile -Force
        exit 0
    }
}
Write-Log 'device did not come back within 240s'
exit 1
