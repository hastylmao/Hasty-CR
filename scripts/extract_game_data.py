"""Extract Clash Royale's own gameplay data from the installed APK.

Why this exists
---------------
The mechanics that matter for a simulator - collision radius, sight range,
deploy time, speed, targeting flags, mass, projectile behaviour - are not
secrets that have to be reverse-engineered out of a private server. They ship
as data files inside the client, because the client is what runs the battle
simulation (Clash Royale uses deterministic lockstep: both clients simulate,
the server validates by replaying inputs).

So the numbers come straight from the horse's mouth, they are exact rather than
community-measured, and re-running this after a balance patch re-syncs
everything automatically - which answers the "constant balance changes" problem
far better than any scraped stats table.

Supercell packs these as LZMA with a 4-byte uncompressed size where the LZMA
alone-format expects 8, so the header needs patching before decompression.
Newer builds also ship per-unit TOML alongside the older CSVs.
"""

from __future__ import annotations

import argparse
import lzma
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADB = Path(r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe")
PACKAGE = "com.supercell.clashroyale"


def decode(blob: bytes) -> Optional[bytes]:
    """Decompress a Supercell data file, or return it unchanged if plain."""
    if not blob:
        return blob
    # Already text?
    if blob[:1].isalpha() or blob[:1] in (b'"', b"#", b"["):
        return blob
    if len(blob) < 9:
        return None
    # Supercell writes 5 props bytes + a 4-byte size; LZMA alone wants 8.
    patched = blob[:9] + b"\x00" * 4 + blob[9:]
    for candidate in (patched, blob):
        try:
            return lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(candidate)
        except lzma.LZMAError:
            continue
    return None


def pull_apks(adb: Path, serial: str, out_dir: Path) -> list[Path]:
    listing = subprocess.run(
        [str(adb), "-s", serial, "shell", "pm", "path", PACKAGE],
        capture_output=True, text=True, timeout=120,
    ).stdout
    paths = [line.split("package:", 1)[1].strip()
             for line in listing.splitlines() if line.startswith("package:")]
    out_dir.mkdir(parents=True, exist_ok=True)
    pulled = []
    for remote in paths:
        local = out_dir / Path(remote).name
        if not local.exists():
            subprocess.run([str(adb), "-s", serial, "pull", remote, str(local)],
                           capture_output=True, timeout=900)
        if local.exists():
            pulled.append(local)
    return pulled


def extract(apks: list[Path], out_dir: Path) -> tuple[int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = failed = 0
    for apk in apks:
        try:
            archive = zipfile.ZipFile(apk)
        except zipfile.BadZipFile:
            continue
        for name in archive.namelist():
            if "csv_logic" not in name and "csv_client" not in name:
                continue
            if name.endswith("/"):
                continue
            decoded = decode(archive.read(name))
            if decoded is None:
                failed += 1
                continue
            target = out_dir / Path(name).relative_to("assets")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(decoded)
            written += 1
    return written, failed


def pull_live_patch(adb: Path, serial: str, out_dir: Path) -> int:
    """Overlay the content Supercell patched in after this APK was built.

    The APK's `csv_logic` is the base. The running client downloads anything
    changed since into `/data/data/<pkg>/update/`, and *that* is what the live
    game plays with - so an extraction from the APK alone is the game as it
    shipped, not the game as it is.

    The delta is usually tiny. At the time this was written it was five files:
    four spirits whose hitpoints went 85 to 84, plus a localisation patch. But
    tiny and absent are different, and there is no way to tell which you have
    without looking.

    Needs a rooted device. MuMu's root toggle is enough - `adb root` restarts
    adbd as uid 0 and no `su` binary is required. Without it this reports that
    it could not read the directory and changes nothing, because the APK data
    on its own is still correct, just possibly one balance patch behind.
    """
    base = f"/data/data/{PACKAGE}/update"
    listing = subprocess.run(
        [str(adb), "-s", serial, "shell", f"find {base} -type f 2>/dev/null"],
        capture_output=True, text=True, timeout=120,
    ).stdout
    remote = [line.strip() for line in listing.splitlines()
              if line.strip().endswith((".toml", ".csv"))]
    if not remote:
        print("no live patch layer readable (device not rooted?); "
              "APK data used as-is")
        return 0

    written = 0
    for path in remote:
        # Relative to update/, so csv_logic/characters/x.toml lands beside the
        # APK's own copy and replaces it.
        rel = path.split(f"{base}/", 1)[-1]
        blob = subprocess.run(
            [str(adb), "-s", serial, "exec-out", f"cat {path}"],
            capture_output=True, timeout=120,
        ).stdout
        decoded = decode(blob)
        if decoded is None:
            continue
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = target.read_bytes() if target.exists() else None
        target.write_bytes(decoded)
        if previous != decoded:
            print(f"  live patch differs: {rel}")
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract CR gameplay data from the APK")
    parser.add_argument("--adb", type=Path, default=DEFAULT_ADB)
    parser.add_argument("--serial", default="127.0.0.1:16480")
    parser.add_argument("--apk-dir", type=Path, default=ROOT / "tmp" / "apk")
    parser.add_argument("--out", type=Path, default=ROOT / "tmp" / "gamedata")
    parser.add_argument("--skip-live-patch", action="store_true",
                        help="APK only; do not overlay the device's update/ layer")
    args = parser.parse_args()

    apks = sorted(args.apk_dir.glob("*.apk"))
    if not apks:
        print("pulling APKs from the device...")
        apks = pull_apks(args.adb, args.serial, args.apk_dir)
    if not apks:
        print("no APKs found; is the emulator connected?")
        return 1

    written, failed = extract(apks, args.out)
    print(f"decoded {written} files to {args.out}  ({failed} undecodable)")

    if not args.skip_live_patch:
        patched = pull_live_patch(args.adb, args.serial, args.out)
        if patched:
            print(f"overlaid {patched} live-patched files from the device")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
