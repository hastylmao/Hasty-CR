$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$vendorRoot = Join-Path $projectRoot "vendor"
$venvRoot = Join-Path $projectRoot ".venvs"

New-Item -ItemType Directory -Force $vendorRoot | Out-Null
New-Item -ItemType Directory -Force $venvRoot | Out-Null

$repositories = [ordered]@{
    "ClashAI" = "https://github.com/vegetableleaf/ClashAI.git"
    "ClashRoyaleBuildABot" = "https://github.com/Pbatch/ClashRoyaleBuildABot.git"
    "py-clash-bot" = "https://github.com/pyclashbot/py-clash-bot.git"
    "KataCR" = "https://github.com/wty-yy/KataCR.git"
    "CRBot-public" = "https://github.com/krazyness/CRBot-public.git"
}

foreach ($entry in $repositories.GetEnumerator()) {
    $target = Join-Path $vendorRoot $entry.Key
    if (-not (Test-Path $target)) {
        git clone --depth 1 $entry.Value $target
    }
}

$clashAiPython = Join-Path $venvRoot "clashai\Scripts\python.exe"
$buildABotPython = Join-Path $venvRoot "buildabot\Scripts\python.exe"
$pyClashBotPython = Join-Path $venvRoot "pyclashbot\Scripts\python.exe"

uv venv (Join-Path $venvRoot "clashai") --python 3.12
uv pip install --python $clashAiPython -r (Join-Path $vendorRoot "ClashAI\icebow\requirements.txt")
uv pip install --python $clashAiPython torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python $clashAiPython -e $projectRoot
uv pip install --python $clashAiPython pytest

uv venv (Join-Path $venvRoot "buildabot") --python 3.12
uv pip install --python $buildABotPython -e (Join-Path $vendorRoot "ClashRoyaleBuildABot[cpu]")

uv venv (Join-Path $venvRoot "pyclashbot") --python 3.12
uv pip install --python $pyClashBotPython -e (Join-Path $vendorRoot "py-clash-bot")
uv pip install --python $pyClashBotPython pytest

Write-Output "Bootstrap complete. Live emulator actions remain disabled in HastyCR by default."

