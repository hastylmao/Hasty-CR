@echo off
rem Double-clickable launcher for the recording studio.
rem
rem Explorer opens .ps1 files in Notepad, so this .cmd exists purely so the
rem studio can be started from a double click instead of a terminal.
rem
rem Pass through any studio.ps1 switch:  studio.cmd -Record -Layout game
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0studio.ps1" %*
echo.
echo studio closed. press any key to exit.
pause >nul
