"""Which emulator this project is allowed to talk to.

Two MuMu instances run on this machine. One plays Clash Royale. The other
runs a Clash of Clans bot, and driving it by accident means taps landing in
somebody's village - so getting this wrong is not a crash, it is damage.

Identity cannot come from the hardware. Both instances report the same spoofed
model (`SM_G9980`), the same 1080x1920, and the same density, because that is
what MuMu presents. It has to come from the instance itself:

    MuMuManager.exe info -v all      lists instances by index and name
    MuMuManager.exe adb -v <index>   gives that instance's adb port

Instance 3 is "Android Device-1-2" and answers on port 16480. Instance 0 is
"Android Device" - the Clash of Clans one - on 16384. The legacy 7555 and 5555
endpoints that this project used to hardcode both resolve to Clash of Clans
instances, which is exactly the bug this module exists to prevent.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_ADB = Path(r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe")

# MuMu instance 3. Override for a different machine with the env vars.
DEFAULT_SERIAL = os.environ.get("HASTYCR_SERIAL", "127.0.0.1:16480")
DEFAULT_INSTANCE = os.environ.get("HASTYCR_INSTANCE", "Android Device-1-2")

REQUIRED_PACKAGE = "com.supercell.clashroyale"
FORBIDDEN_PACKAGE = "com.supercell.clashofclans"


def packages(serial: str = DEFAULT_SERIAL, adb: str | Path = DEFAULT_ADB) -> set[str]:
    """Every package installed on `serial`, or an empty set if unreachable."""
    try:
        out = subprocess.run([str(adb), "-s", serial, "shell", "pm", "list", "packages"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip().replace("package:", "")
            for line in out.stdout.splitlines() if line.strip()}


def verify(serial: str = DEFAULT_SERIAL, adb: str | Path = DEFAULT_ADB) -> None:
    """Raise unless `serial` is the Clash Royale instance.

    Called before anything sends a tap. A wrong serial used to be silent: the
    bot would connect, fail to recognise the screen, and keep tapping - into
    Clash of Clans. Better to refuse to start than to play someone else's
    game.
    """
    found = packages(serial, adb)
    if not found:
        raise SystemExit(
            f"cannot reach {serial}. Start the emulator, or run:\n"
            f'  "{adb}" connect {serial}\n'
            f"Ports come from: MuMuManager.exe adb -v <instance index>")
    if FORBIDDEN_PACKAGE in found and REQUIRED_PACKAGE not in found:
        raise SystemExit(
            f"refusing to run: {serial} is the CLASH OF CLANS instance.\n"
            f"That device runs another bot and must not be driven from here.\n"
            f"The Clash Royale instance is {DEFAULT_SERIAL} "
            f'(MuMu instance "{DEFAULT_INSTANCE}").')
    if REQUIRED_PACKAGE not in found:
        raise SystemExit(
            f"refusing to run: {REQUIRED_PACKAGE} is not installed on {serial}.\n"
            f"Expected the Clash Royale instance at {DEFAULT_SERIAL} "
            f'("{DEFAULT_INSTANCE}").')


if __name__ == "__main__":                      # a quick check from the shell
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SERIAL
    verify(target)
    print(f"{target} is the Clash Royale instance ({DEFAULT_INSTANCE})")
