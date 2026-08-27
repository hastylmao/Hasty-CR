"""Recording studio: one portrait canvas holding the game, the brain and the log.

Run it with `python -m scripts.studio`, or `.\\studio.ps1` from the repo root.

It is strictly an observer.  Frames come from `PrintWindow` on the emulator's
render surface and state comes from tailing `tmp/live/cr_bot.log`, so the studio
never touches ADB, never taps, and cannot disturb a match in progress.
"""
