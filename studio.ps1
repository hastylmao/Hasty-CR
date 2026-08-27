# Open the recording studio: the emulator mirrored at 60fps next to the bot's
# own decisions, in a 1080x1920 portrait canvas made for Shorts and Reels.
#
#   .\studio.ps1                 mirror + brain rail + log feed, detector on
#   .\studio.ps1 -Record         start recording to tmp\live\studio immediately
#   .\studio.ps1 -Layout game    bigger mirror, shorter log
#   .\studio.ps1 -Layout feed    smaller mirror, longer log
#   .\studio.ps1 -NoDetect       skip YOLO (leaves the GPU to training)
#   .\studio.ps1 -List           list emulator surfaces and exit
#
# It is read-only: frames come from the emulator window, state from tailing
# tmp\live\cr_bot.log. Starting or closing it cannot disturb a live match.
#
# In the window:  R record  S still  L labels  D detector  F fullscreen  Q quit

param(
    [switch]$Record,
    [ValidateSet('balanced', 'game', 'feed')][string]$Layout = 'balanced',
    [switch]$NoDetect,
    [int]$Fps = 60,
    [double]$Scale = 0.52,
    [switch]$List
)

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
# python, not pythonw: the startup summary and the REC lines go to the console,
# and pythonw would detach stdout and swallow them.
$python = Join-Path $root '.venvs\buildabot\Scripts\python.exe'

$studioArgs = @('-u', '-m', 'scripts.studio', '--layout', $Layout,
                '--fps', $Fps, '--scale', $Scale)
if ($List)     { $studioArgs += '--list' }
if ($Record)   { $studioArgs += '--record' }
if ($NoDetect) { $studioArgs += '--no-detect' }

$env:PYTHONIOENCODING = 'utf-8'
Push-Location $root
try { & $python @studioArgs } finally { Pop-Location }
