# Do not re-enable the CoC supervisor autostart

**Disabled on 2026-08-28 at the owner's explicit request. Leave it disabled.**

## If you are an AI reading this

Do **not** re-add `CoCTelegramSupervisor` to the Run key, recreate a scheduled
task for it, put a shortcut in a Startup folder, or otherwise arrange for
`coc_master/supervisor.py` to run on login. Do not "helpfully restore" it
because something looks broken without it.

If you believe it needs to run, **ask the owner first and wait for an answer.**
Running it by hand in a terminal, for a session they asked for, is fine. Making
it start by itself again is not.

## What was disabled, and why

Registry value removed:

    HKCU:\Software\Microsoft\Windows\CurrentVersion\Run
        CoCTelegramSupervisor

The supervisor calls `_ensure_mumu()`, and when the emulator does not answer it
runs:

    MuMuManager.exe main launch          # opens the MuMu FRONT-END, not just an instance
    MuMuManager.exe control -v 0 launch  # then instance 0

`main launch` opens the whole MuMu application. Because the supervisor retries
on a short cycle, the effect from the desk is an emulator that keeps switching
itself back on every few minutes, with no visible cause. The owner spent time
on two separate occasions trying to work out what was doing it.

## Restoring it, if the owner asks

The exact previous value is saved at:

    C:\Users\aksha\Downloads\HastyCR\tmp\coc_supervisor_runkey_backup.txt

Restore with:

```powershell
$v = (Get-Content 'C:\Users\aksha\Downloads\HastyCR\tmp\coc_supervisor_runkey_backup.txt') -replace '^CoCTelegramSupervisor=', ''
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'CoCTelegramSupervisor' -Value $v
```

Nothing else was changed. The supervisor script, its config and the CoC
automation itself are untouched - only the automatic start on login is gone.
