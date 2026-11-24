"""Read-only access to the Clash Royale process on MuMu instance 3.

Nothing here writes to the game, injects code, or sends input. It reads
`/proc/<pid>/mem` through `adb shell` (MuMu's "ADB Root" setting must be on),
which is what the kernel offers any root process.

Guards, all checked before the first read:
* the device is the Clash Royale instance (`scripts/emulator.verify`);
* the installed client is exactly the build the offsets belong to: versionCode
  and the SHA-256 of `libg.so` (`IDENTITY`). Any other build is refused - the
  offsets would point at something else and every value read would be wrong.

This is the slow path: one `adb` round trip per read, tens of milliseconds.
It exists to validate offsets and structure. The live reader batches a whole
frame in one call (`snapshot`) and a native helper is the next step.

Offsets: the pointer chain and field layout for build 160402012 come from
vegetableleaf's public ClashAI repo - the summary in
scratchpad/gauntlet/L70/reader/FINDINGS.md and the field tables in his reader
sources (L70/reader/live_sampler2.c, L72/.../live_sampler3.c: player elixir,
hand and cycle vectors, unit data-name chain). His repo has no licence; no
code was copied, our readers are written here, but the offsets are his
findings. Every one is re-verified against the live process before use
(`probe`); which player record is ours was found here (2026-10-10).
"""

from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from emulator import DEFAULT_ADB, DEFAULT_SERIAL, verify  # noqa: E402

PACKAGE = "com.supercell.clashroyale"
IDENTITY = {
    "version_code": "160402012",
    "libg_sha256": "79c4e485a4e730db4482a08d625d92ddfccaceee2033ee6c55046b57088918c2",
}
# libg-relative global, then the hops to the battle object (FINDINGS.md).
BATTLE_GLOBAL = 0x1AEEF98
BATTLE_HOPS = (0x18, 0x90)


class Refused(SystemExit):
    pass


def _sh(cmd: str, serial: str = DEFAULT_SERIAL, binary: bool = False, timeout: int = 20):
    out = subprocess.run([str(DEFAULT_ADB), "-s", serial, "exec-out", cmd],
                         capture_output=True, timeout=timeout)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


OFFSETS = Path(__file__).with_name("offsets.json")


def known_builds() -> dict:
    return json.loads(OFFSETS.read_text())["builds"]


class GameMemory:
    def __init__(self, serial: str = DEFAULT_SERIAL, allow_new: bool = False):
        verify(serial)
        self.serial = serial
        if _sh("id -u", serial).strip() != "0":
            raise Refused("adb is not root: enable MuMu's 'ADB Root' on instance 3 only")
        version = _sh(f"dumpsys package {PACKAGE} | grep -m1 versionCode", serial)
        m = re.search(r"versionCode=(\d+)", version)
        self.version = m.group(1) if m else "?"
        builds = known_builds()
        self.offsets = builds.get(self.version)
        if self.offsets is None and not allow_new:
            raise Refused(f"client build {self.version} has no offsets yet (known: {sorted(builds)}); "
                          f"live_play finds them in the first battle")
        pid = _sh(f"pidof {PACKAGE}", serial).strip()
        if not pid:
            raise Refused("Clash Royale is not running")
        self.pid = int(pid.split()[0])
        maps = _sh(f"grep libg.so /proc/{self.pid}/maps", serial).splitlines()
        if not maps:
            raise Refused("libg.so is not mapped")
        path = maps[0].split()[-1]
        self.libg_sha = _sh(f"sha256sum {path}", serial).split()[0]
        if self.offsets is not None and self.libg_sha != self.offsets["libg_sha256"]:
            raise Refused(f"libg.so hash {self.libg_sha} is not the pinned build {self.version}")
        self.libg = min(int(line.split("-")[0], 16) for line in maps)
        # libg's writable mappings and its .bss (an anonymous "[anon:.bss]"
        # mapping right after them): where the battle global lives. Build
        # 160635007 put it in .bss (libg+0x1c0f6e8, found live 2026-11-07).
        full = _sh(f"cat /proc/{self.pid}/maps", serial).splitlines()
        self.rw, prev_libg = [], False
        for line in full:
            f = line.split()
            if len(f) < 2:
                continue
            is_libg = line.rstrip().endswith("libg.so")
            if f[1].startswith("rw") and (is_libg or (prev_libg and "[anon:.bss]" in line)):
                self.rw.append(tuple(int(x, 16) for x in f[0].split("-")))
            prev_libg = is_libg or (prev_libg and "[anon:.bss]" in line)

    @property
    def known(self) -> bool:
        return self.offsets is not None

    def reader_env(self) -> str:
        """Environment for hcr_reader: this build's global and hops."""
        o = self.offsets
        return f"HCR_GLOBAL={o['global']} HCR_HOP1={o['hops'][0]} HCR_HOP2={o['hops'][1]}"

    def find_battle(self) -> list:
        """Candidate (global, hop1, hop2, tick) chains to a live battle, via the
        on-device probe (/data/local/tmp/hcr_findbattle; read-only, small reads).
        Empty outside a battle."""
        out = []
        for lo, hi in self.rw:
            for line in _sh(f"/data/local/tmp/hcr_findbattle {self.pid} {lo:x} {hi:x} {self.libg:x}",
                            self.serial, timeout=120).splitlines():
                parts = line.split()
                if len(parts) == 4 and parts[0] != "done":
                    out.append((int(parts[0], 16), int(parts[1], 16), int(parts[2], 16), int(parts[3])))
        return out

    def learn_build(self, g: int, h1: int, h2: int, note: str) -> None:
        """Save offsets found live for this build and use them from now on."""
        data = json.loads(OFFSETS.read_text())
        data["builds"][self.version] = {"global": hex(g), "hops": [hex(h1), hex(h2)],
                                        "libg_sha256": self.libg_sha, "source": note}
        tmp = OFFSETS.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1) + "\n")
        tmp.replace(OFFSETS)
        self.offsets = data["builds"][self.version]

    def read(self, addr: int, size: int) -> bytes:
        if addr <= 0:
            return b""
        cmd = (f"dd if=/proc/{self.pid}/mem bs=4096 iflag=skip_bytes,count_bytes "
               f"skip={addr} count={size} 2>/dev/null")
        return _sh(cmd, self.serial, binary=True)

    def u64(self, addr: int) -> int:
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if len(b) == 8 else 0

    def battle(self) -> int:
        """Address of the battle object, or 0 outside a battle."""
        p = self.u64(self.libg + int(self.offsets["global"], 16))
        for hop in (int(h, 16) for h in self.offsets["hops"]):
            if not p:
                return 0
            p = self.u64(p + hop)
        return p


def probe() -> Dict[str, object]:
    g = GameMemory()
    first = g.u64(g.libg + BATTLE_GLOBAL)
    hop1 = g.u64(first + BATTLE_HOPS[0]) if first else 0
    return {"pid": g.pid, "libg": hex(g.libg), "global": hex(first),
            "hop1": hex(hop1), "battle": hex(g.battle())}


if __name__ == "__main__":
    for k, v in probe().items():
        print(f"{k:8} {v}")
