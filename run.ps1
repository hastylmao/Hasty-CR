# Launch the Clash Royale bot.
#
#   .\run.ps1                 play 5 matches, then stop
#   .\run.ps1 -Matches 20     play 20 matches
#   .\run.ps1 -Brain rl -NoQueue -Matches 3
#                             friendly 1v1: you start the battle, it plays
#   .\run.ps1 -Forever        run the supervisor loop: blocks of 5, reviewed
#                             and tuned between blocks, until stopped
#   .\run.ps1 -Stop           stop everything
#
# Requires MuMu running with Clash Royale open. The advisor needs Ollama, which
# is checked below rather than left to fail silently mid-match.

param(
    [int]$Matches = 5,
    [double]$Hours = 2.0,
    [switch]$Forever,
    [switch]$Stop,
    [switch]$NoAdvisor,
    # Unit perception. 'yolo' is the detector trained here (0.959 mAP50) plus
    # the ally/enemy classifier (94.0%); measured on live frames it is 2.2x
    # faster than upstream (20.7ms vs 45.3ms) and does not report a Baby Dragon
    # as the most common unit in a Hog 2.6 mirror. 'buildabot' reverts.
    [ValidateSet('yolo', 'buildabot')][string]$Vision = 'yolo',
    # Who decides what to play.
    #
    #   rules  - the hand-written policy in brain/policy.py, optionally biased
    #            by the local Qwen advisor (see -NoAdvisor). This is what has
    #            been playing ladder.
    #   rl     - a policy trained in the simulator, deciding every play itself.
    #            The advisor is not consulted at all in this mode: it can only
    #            reweight candidates a rule engine produced, and in rl mode
    #            there is no rule engine in the decision path.
    #
    # Perception is shared either way - detection, unit tracking, hand
    # smoothing and the elixir model are the same code. Only judgement changes.
    # Keep the emulator at its native 1080x1920 instead of dropping it to
    # 540x960 for capture speed. Slower per decision, but the mirror, any
    # screen recording and anything else sharing this instance stay sharp.
    # Use it when the run is going into a video rather than into trophies.
    [switch]$FullRes,
    # Re-enable the HastyCR scheduled tasks alongside -Forever. Off by default:
    # they persist after the run and fire every few minutes forever, and the
    # emulator watchdog restarts Clash Royale on its own schedule.
    [switch]$Watchdogs,
    [ValidateSet('rules', 'rl')][string]$Brain = 'rules',
    # Play, but never press Battle. For a friendly 1v1: you start the match
    # from your side and the bot plays whatever it finds itself in, because
    # the runner decides it is in a game from the screen rather than from
    # having queued one. Without this it would keep tapping Battle in the
    # lobby and drag itself into ladder between your friendlies.
    [switch]$NoQueue,
    # The frozen Sprint 3 winner: step 4,392,960, 43.3% against the rule engine
    # over 300 held-out games (Wilson 37.8-49.0), 91% vs meta decks, 100% vs
    # simple, 0% illegal actions. checkpoints/sprint4_baseline/manifest.json has
    # the hyperparameters, the sha256 and the full eval.
    #
    # This used to point at tmp\rl\hog26v6_best.pt, which was a collapsed run -
    # one win in fifty-nine. Checkpoints under tmp\ are scratch and get
    # overwritten by whatever is training; anything meant to touch a real ladder
    # match lives under checkpoints\ with a manifest saying what it scored.
    [string]$Checkpoint = 'checkpoints\sprint4_baseline\pilot_best_4392960.pt'
)

$ErrorActionPreference = 'Continue'
$root   = $PSScriptRoot
$python = Join-Path $root '.venvs\buildabot\Scripts\python.exe'
$adb    = 'C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe'
$serial = '127.0.0.1:7555'

if ($Stop) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*cr_bot.py*' -or $_.CommandLine -like '*supervisor.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "stopped pid $($_.ProcessId)" }
    Disable-ScheduledTask -TaskName 'HastyCR-Watchdog' -ErrorAction SilentlyContinue | Out-Null
    Disable-ScheduledTask -TaskName 'HastyCR-Captain'  -ErrorAction SilentlyContinue | Out-Null
    Write-Host 'stopped.' -ForegroundColor Yellow
    exit 0
}

# The emulator has to be reachable before anything else is worth trying.
# Note the -join: `-match` against an array filters it rather than returning a
# boolean, so comparing the array directly always looks like a mismatch.
$devices = (& $adb devices 2>$null) -join "`n"
if ($devices -notmatch [regex]::Escape($serial)) {
    Write-Host "emulator not found at $serial - is MuMu running?" -ForegroundColor Red
    & $adb connect $serial | Out-Null
    Start-Sleep -Seconds 2
    if (((& $adb devices 2>$null) -join "`n") -notmatch [regex]::Escape($serial)) { exit 1 }
}

$focus = ((& $adb -s $serial shell dumpsys window 2>$null) -join "`n")
if ($focus -notmatch 'clashroyale') {
    Write-Host 'Clash Royale is not in the foreground - open it first.' -ForegroundColor Yellow
}

# Half resolution, because a raw screencap costs transfer time and nothing else:
# 1080x1920 is 8.3MB and ~406ms, 540x960 is 2.07MB and ~117ms, and capture was
# 90% of the whole decision loop. The bot normalises frames back to 1080x1920
# and scales taps, so this is purely a speed setting - it reverts on its own if
# the emulator restarts, which is why it is re-applied on every launch.
# It is restored on the way out, always. This used to be set and left set, and
# `wm size` is a property of the *device*, not of this bot: MuMu's own settings
# and Instance Manager keep reporting the physical 1080x1920 while the surface
# renders at a quarter of it, so there is nothing on screen to tell you. It
# quietly cost every recording its quality and broke a different bot on the
# same emulator that reasonably expected the resolution it had configured.
$displayChanged = $false
if ($FullRes) {
    if (((& $adb -s $serial shell wm size 2>$null) -join "`n") -match 'Override size') {
        & $adb -s $serial shell wm size reset | Out-Null
        Start-Sleep -Seconds 2
    }
    Write-Host 'display: native 1080x1920 (-FullRes) - slower capture, sharp mirror' -ForegroundColor Cyan
} else {
    $size = ((& $adb -s $serial shell wm size 2>$null) -join "`n")
    if ($size -notmatch '540x960') {
        & $adb -s $serial shell wm size 540x960 | Out-Null
        Start-Sleep -Seconds 2
        $displayChanged = $true
        Write-Host 'display set to 540x960 for capture speed; restored on exit. Use -FullRes to keep it native.' -ForegroundColor DarkGray
    }
}

function Restore-Display {
    if ($script:displayChanged) {
        & $adb -s $serial shell wm size reset | Out-Null
        Write-Host 'display restored to 1080x1920' -ForegroundColor DarkGray
        $script:displayChanged = $false
    }
}

# The advisor only ever biases the rule engine's candidates, so in rl mode
# there is nothing for it to bias. Checking Ollama and then reporting
# "advisor: on" for a run that never calls it would be a lie in the log.
$useAdvisor = (-not $NoAdvisor) -and ($Brain -eq 'rules')
if ($useAdvisor) {
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Out-Null }
    catch {
        Write-Host 'Ollama not responding; running on rules only.' -ForegroundColor Yellow
        $useAdvisor = $false
    }
}

$checkpointPath = $Checkpoint
if (-not [System.IO.Path]::IsPathRooted($checkpointPath)) {
    $checkpointPath = Join-Path $root $Checkpoint
}
if ($Brain -eq 'rl' -and -not (Test-Path $checkpointPath)) {
    # Refuse rather than silently fall back to the rules. Being handed the
    # wrong brain without being told is worse than not starting.
    Write-Host "no checkpoint at $checkpointPath" -ForegroundColor Red
    Write-Host 'train one, or pass -Checkpoint <path>' -ForegroundColor Yellow
    exit 1
}

if ($Forever) {
    # Opt-in, because these are Windows scheduled tasks that outlive the run.
    # They fire every few minutes whether or not this project is open, and one
    # of them relaunches the emulator - which reads as the machine deciding on
    # its own to start Clash Royale, with a console flashing each time. Nothing
    # on screen connects that to a bot you ran days earlier, so turning them on
    # as a side effect of -Forever is not a reasonable default.
    if ($Watchdogs) {
        Enable-ScheduledTask -TaskName 'HastyCR-Watchdog' -ErrorAction SilentlyContinue | Out-Null
        Enable-ScheduledTask -TaskName 'HastyCR-Captain'  -ErrorAction SilentlyContinue | Out-Null
        Write-Host 'watchdog + captain enabled (-Watchdogs); .\run.ps1 -Stop disables them' -ForegroundColor Yellow
    }
    Write-Host 'starting supervisor: blocks of 5 matches, reviewed between blocks' -ForegroundColor Green
    Write-Host 'watch it with:  Get-Content tmp\live\cr_bot.log -Wait -Tail 20'
    Write-Host 'stop it with:   .\run.ps1 -Stop'
    $supervisorArgs = @((Join-Path $root 'scripts\supervisor.py'))
    if ($Brain -eq 'rl') { $supervisorArgs += @('--rl', $checkpointPath) }
    try {
        & $python @supervisorArgs
        $code = $LASTEXITCODE
    } finally {
        Restore-Display
    }
    exit $code
}

$botArgs = @(
    (Join-Path $root 'scripts\cr_bot.py'),
    '--adb', $adb, '--serial', $serial,
    '--max-matches', $Matches, '--hours', $Hours,
    '--vision', $Vision
)
# --harvest-sprites gathers reference crops of units as they appear on this
# device. It was off because the crops were labelled by the *old* detector and
# inherited its mistakes - spell particles filed as Bats. The detector is now
# the one trained here (P 0.949 / R 0.926), so the labels are worth having.
#
# Note what this does and does not do: MAX_PER_CLASS is 6, so it collects about
# 1200 small crops and then stops. That is reference art for eyeballing what a
# class actually looks like on this screen. It is not a training set, and no
# amount of extra running time makes it one - for that, use the published
# datasets. These crops must also never be trained on directly: the labels come
# from our own detector, so training on them would only teach it its own errors.
$botArgs += '--harvest-sprites'
if ($useAdvisor) { $botArgs += '--advisor' }
if ($NoQueue)    { $botArgs += '--no-queue' }
if ($Brain -eq 'rl') { $botArgs += @('--rl', $checkpointPath) }

$who = if ($Brain -eq 'rl') {
    "simulator-trained ($(Split-Path $checkpointPath -Leaf))"
} else {
    "rules (advisor: $(if($useAdvisor){'on'}else{'off'}))"
}
Write-Host "playing $Matches matches - brain: $who" -ForegroundColor Green
$env:PYTHONIOENCODING = 'utf-8'
# finally, so Ctrl+C leaves the emulator as it was found. A crash or an
# interrupt is exactly when the old code left the display at 540x960 for
# whatever ran next.
try {
    & $python @botArgs
} finally {
    Restore-Display
}
