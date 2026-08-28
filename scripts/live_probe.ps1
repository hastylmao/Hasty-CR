$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venvs\buildabot\Scripts\python.exe"
$adb = "C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe"
$frame = Join-Path $projectRoot "tmp\live\clash-royale.png"

& $python (Join-Path $PSScriptRoot "live_probe.py") `
    --adb $adb `
    --serial "127.0.0.1:16480" `
    --save-frame $frame

exit $LASTEXITCODE
