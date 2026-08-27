@echo off
rem Double-clickable launcher for the bot: blocks of 5 matches, reviewed and
rem tuned between blocks, until this window is closed.
rem
rem MuMu has to be running with Clash Royale open first.
rem
rem   bot.cmd                 the supervisor loop (default)
rem   bot.cmd -Matches 5      play 5 matches then stop
rem   bot.cmd -Stop           stop everything that is running
cd /d "%~dp0"
if "%~1"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -Forever
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
)
echo.
echo bot stopped. press any key to exit.
pause >nul
