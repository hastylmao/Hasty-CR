$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonExe = Join-Path $projectRoot ".venvs\buildabot\Scripts\python.exe"
$runner = Join-Path $projectRoot "scripts\mumu_katacr.py"
$adbExe = "C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe"
$checkpoint = Join-Path $projectRoot "vendor\KataCR\logs\Policy\StARformer_3L_v0.8_golem_ai_cnn_blocks__nbc128__ep30__step50__0__20240512_181646\ckpt"
$logDir = Join-Path $projectRoot "tmp\live"
$runLog = Join-Path $logDir "katacr_overnight.log"
$supervisorLog = Join-Path $logDir "katacr_supervisor.log"
$deadline = (Get-Date).AddHours(8)

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $projectRoot

while ((Get-Date) -lt $deadline) {
    $remainingHours = ($deadline - (Get-Date)).TotalHours
    Add-Content -Path $supervisorLog -Value "$(Get-Date -Format s) START remaining_hours=$([math]::Round($remainingHours, 3))"
    & $pythonExe $runner `
        --adb $adbExe `
        --serial "127.0.0.1:7555" `
        --checkpoint $checkpoint `
        --epoch 3 `
        --hours $remainingHours `
        --auto-queue `
        --log $runLog
    $exitCode = $LASTEXITCODE
    Add-Content -Path $supervisorLog -Value "$(Get-Date -Format s) EXIT code=$exitCode"
    if ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
    }
}

Add-Content -Path $supervisorLog -Value "$(Get-Date -Format s) COMPLETE"
