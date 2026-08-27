"""Mirror every public Clash Royale dataset RoyaleAPI publishes, with provenance.

The project synced exactly one file, `cards.json`, which carries card identity
and elixir cost and nothing else. The same source publishes about thirty-seven,
including the full per-level stat tables, every projectile's speed and homing
flag, and the spell parameters. Several things were being treated as "needs a
live measurement" that are simply sitting in a file nobody fetched:

    projectile speed and homing        cards_stats_projectile
    whether a shot clips things        check_collisions, same file
    tower damage and hitpoints by level cards_stats_building, damage_per_level
    spell radius, duration, damage      cards_stats_spell

What this source does *not* carry is the tower troops - Dagger Duchess,
Cannoneer, Royal Chef. Those are only in the extracted client data, under
`characters/`, and they matter: Dagger Duchess fires every 500ms against a
Princess Tower's 800ms.

Every file is stored with its SHA-256, its URL and the time it was fetched, so
a number taken from here can be traced later. That is the same contract
`combat_rules.json` uses for hand-checked values.

    python scripts/sync_royaleapi_full.py
    python scripts/sync_royaleapi_full.py --check    # report drift, write nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "royaleapi"
BASE = "https://royaleapi.github.io/cr-api-data/json/"

# Everything with simulation value. Cosmetic and progression sets (emotes,
# season passes, trophy road) are deliberately not mirrored.
# `cards.json` is deliberately absent: `sync_royaleapi_cards.py` already owns
# that file and stores it wrapped in its own provenance envelope
# ({source, retrieved_at, sha256, cards}). Mirroring the raw list over the top
# of it breaks every reader in the project.
DATASETS = [
    "cards_evo",                   # evolution card rows
    "cards_stats_troop",           # troop stats, some per-level tables
    "cards_stats_building",        # buildings and both towers, per-level
    "cards_stats_spell",           # spell radius, duration, damage
    "cards_stats_projectile",      # speed, homing, check_collisions, damage
    "cards_stats_characters",      # the full character table
    "cards_stats_character_buff",  # buff definitions
    "buildings_evo",
    "projectiles_evo",
    "rarities",                    # the level multiplier tables
    "exp_levels",
    "arenas",
]

TIMEOUT = 30


def fetch(name: str) -> bytes:
    url = BASE + name + ".json"
    request = urllib.request.Request(url, headers={"User-Agent": "HastyCR sync"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # nosec B310
        return response.read()


def _shape(payload) -> str:
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    if isinstance(payload, dict):
        inner = ", ".join(f"{key}:{len(value)}" for key, value in payload.items()
                          if hasattr(value, "__len__"))
        return f"dict({inner})" if inner else "dict"
    return type(payload).__name__


def sync(check_only: bool = False) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "datasets.json"
    previous = {}
    if manifest_path.exists():
        try:
            previous = {row["dataset"]: row for row
                        in json.loads(manifest_path.read_text(encoding="utf-8"))["datasets"]}
        except (OSError, ValueError, KeyError):
            previous = {}

    rows, failures, changed = [], [], []
    for name in DATASETS:
        try:
            raw = fetch(name)
            payload = json.loads(raw)
        except Exception as error:                            # noqa: BLE001
            failures.append(f"{name}: {type(error).__name__}: {error}")
            continue
        digest = hashlib.sha256(raw).hexdigest()
        row = {"dataset": name, "url": BASE + name + ".json",
               "sha256": digest, "bytes": len(raw), "shape": _shape(payload)}
        was = previous.get(name, {}).get("sha256")
        if was and was != digest:
            changed.append(name)
        rows.append(row)
        if not check_only:
            (OUT / f"{name}.json").write_bytes(raw)

    manifest = {
        "source": BASE,
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "datasets": rows,
    }
    if not check_only:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                                 encoding="utf-8")
    return {"manifest": manifest, "failures": failures, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report drift against the stored manifest, write nothing")
    args = parser.parse_args()

    result = sync(check_only=args.check)
    total = sum(row["bytes"] for row in result["manifest"]["datasets"])
    print(f"{len(result['manifest']['datasets'])} datasets, {total:,} bytes")
    for row in result["manifest"]["datasets"]:
        print(f"  {row['dataset']:28s} {row['bytes']:>9,}B  {row['shape']}")

    if result["changed"]:
        print(f"\nCHANGED since the last sync: {', '.join(result['changed'])}")
        print("A stat that moved is a balance change. Re-run the audits before "
              "trusting a number that depends on it.")
    if result["failures"]:
        print(f"\nFAILED: {len(result['failures'])}")
        for line in result["failures"]:
            print(f"  {line}")
        return 1
    if args.check:
        print("\n(--check: nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
