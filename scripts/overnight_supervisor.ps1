$ErrorActionPreference = "Continue"

# Autonomous overnight loop. Runs blocks of 5 matches, analyses each block,
# restarts the bot on any crash, and keeps the capture daemon alive.
# Deliberately model-free: nothing here needs an AI to be awake.

$root       = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$py         = Join-Path $root ".venvs\buildabot\Scripts\python.exe"
$runner     = Join-Path $root "scripts\mumu_katacr.py"
$capture    = Join-Path $root "scripts\capture_daemon.py"
$analyzer   = Join-Path $root "scripts\analyze_run.py"
$reviewer   = Join-Path $root "scripts\peer_review.py"
$adb        = "C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe"
$serial     = "127.0.0.1:16480"

$liveDir    = Join-Path $root "tmp\live"
$frameDir   = Join-Path $root "tmp\live\frames"
$blockDir   = Join-Path $root "tmp\live\blocks"
$report     = Join-Path $liveDir "overnight_report.txt"
$supLog     = Join-Path $liveDir "supervisor.log"
$reviewDir  = Join-Path $liveDir "reviews"

New-Item -ItemType Directory -Force -Path $liveDir, $frameDir, $blockDir, $reviewDir | Out-Null

$mutex = New-Object System.Threading.Mutex($false, "Global\HastyCR_OvernightSupervisor")
if (-not $mutex.WaitOne(0)) {
    Add-Content -Path $supLog -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') SUPERVISOR another instance is already running; exiting" -Encoding utf8
    exit 0
}

Set-Location $root

function Write-Sup($message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
    Add-Content -Path $supLog -Value $line -Encoding utf8
    Write-Output $line
}

# Capture daemon: one instance, restarted if it ever dies.
function Ensure-Capture {
    $running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*capture_daemon.py*" }
    if (-not $running) {
        Start-Process -FilePath $py -ArgumentList @(
            $capture, "--adb", "`"$adb`"", "--serial", $serial,
            "--out", "`"$frameDir`"", "--interval", "3",
            "--width", "360", "--quality", "55", "--budget-mb", "1500"
        ) -WindowStyle Hidden
        Write-Sup "CAPTURE started"
    }
}

function Stop-StaleWorkers {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -like "*$root*scripts*mumu_katacr.py*" -or
            $_.CommandLine -like "*$root*scripts*capture_daemon.py*" -or
            $_.CommandLine -like "*$root*scripts*peer_review.py*"
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Sup "STALE stopped pid=$($_.ProcessId)"
        }
}

function Start-PeerReview($blockLog) {
    $running = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*$root*scripts*peer_review.py*" }
    if ($running) {
        Write-Sup "REVIEW skip existing peer_review process"
        return
    }
    Start-Process -FilePath $py -ArgumentList @(
        $reviewer, "`"$blockLog`"", "--out-dir", "`"$reviewDir`"",
        "--providers", "claude,opencode,agy"
    ) -WindowStyle Hidden
    Write-Sup "REVIEW started_async log=$blockLog"
}

Write-Sup "SUPERVISOR start root=$root"
Stop-StaleWorkers

# Continue numbering from whatever already exists. A restart used to reset this
# to 0, which appended a fresh run into block_001.log and mixed two different
# policies inside one file.
$existing = Get-ChildItem -Path $blockDir -Filter "block_*.log" -ErrorAction SilentlyContinue |
    ForEach-Object { [int]($_.BaseName -replace 'block_', '') } |
    Sort-Object -Descending | Select-Object -First 1
$block = if ($existing) { $existing } else { 0 }
Write-Sup "SUPERVISOR numbering resumes after block $block"

while ($true) {
    $block++
    & $adb connect $serial | Out-Null
    Ensure-Capture

    $blockLog = Join-Path $blockDir ("block_{0:D3}.log" -f $block)
    Write-Sup "BLOCK $block start log=$blockLog"

    & $py $runner `
        --adb $adb `
        --serial $serial `
        --epoch 3 `
        --hours 2 `
        --auto-queue `
        --shims `
        --max-matches 5 `
        --log $blockLog

    $code = $LASTEXITCODE
    Write-Sup "BLOCK $block bot_exit=$code"

    if (Test-Path $blockLog) {
        Add-Content -Path $report -Value "`n### BLOCK $block  ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))" -Encoding utf8
        & $py $analyzer $blockLog --out $report | Out-Null
        Write-Sup "BLOCK $block analysed -> $report"
        Start-PeerReview $blockLog
    }

    Start-Sleep -Seconds 5
}
