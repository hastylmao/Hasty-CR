"""Cross-check every public RoyaleAPI card against extracted client data.

RoyaleAPI uses player-facing keys (``the-log``), while client data uses the
runtime character key (``log``) or a legacy implementation name
(``BlowdartGoblin``). The public ``sc_key`` is the bridge between them.

    python -m sim.card_catalog_audit
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "royaleapi" / "cards.json"
NORMALIZE = re.compile(r"[^a-z0-9]+")


def canonical(value: str) -> str:
    """Normalize separator/case differences used by the two data sets."""
    return NORMALIZE.sub("", value.lower())


def report() -> dict[str, object]:
    from .gamedata import load_gamedata

    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    cards = payload.get("cards")
    if not isinstance(cards, list):
        raise ValueError("public card snapshot has no cards list")
    local = load_gamedata(level=11)
    local_by_key: dict[str, list[str]] = defaultdict(list)
    for local_name in local:
        local_by_key[canonical(local_name)].append(local_name)

    mapping: dict[str, str] = {}
    unresolved: list[str] = []
    ambiguous: dict[str, list[str]] = {}
    for card in cards:
        if not isinstance(card, dict) or not isinstance(card.get("key"), str):
            raise ValueError("public card snapshot contains an invalid card")
        runtime_key = card.get("sc_key")
        candidates = (local_by_key.get(canonical(runtime_key), [])
                      if isinstance(runtime_key, str) else [])
        if len(candidates) == 1:
            mapping[card["key"]] = candidates[0]
        elif not candidates:
            unresolved.append(card["key"])
        else:
            ambiguous[card["key"]] = sorted(candidates)
    return {
        "public_cards": len(cards),
        "mapped": mapping,
        "unresolved": sorted(unresolved),
        "ambiguous": dict(sorted(ambiguous.items())),
    }


def main() -> int:
    result = report()
    print(f"public cards: {result['public_cards']}")
    print(f"mapped to client data: {len(result['mapped'])}")
    print(f"unresolved public cards: {result['unresolved']}")
    print(f"ambiguous public cards: {result['ambiguous']}")
    return 0 if not result["unresolved"] and not result["ambiguous"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
