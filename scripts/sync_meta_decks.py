"""Build an opponent deck pool from real Path of Legends battle logs.

The simulator's opponent problem, stated in `sim/train_ppo.py`'s own words:

    the mirror defends exactly as well as we attack, and `SimpleOpponent`
    loses 99.7% of the time. Every sweep run here has therefore answered
    "does this beat a copy of me", which is not the question.

Training against one deck - especially our own - teaches a policy to beat that
deck. A pool of real ladder decks is the difference between an agent that
counters Hog Cycle and an agent that has seen a Golem, a Three Musketeers split
and a Miner-Poison control deck and knows they are different problems.

**Where the decks come from.** RoyaleAPI's popular-decks page returns 403 to
automated access and is not scraped here. Instead this reads a public dataset
of real battle logs on Hugging Face, MIT licensed:

    https://huggingface.co/datasets/raymond9326/clash-royale-battles

Each row is one battle with both players' eight cards, the game mode and the
arena. Filtering to `pathOfLegend` - the competitive ladder - and counting
which eight-card combinations actually appear gives a meta ranking that is
observed rather than asserted.

**Coverage is enforced separately.** The top decks by usage will not contain
every card; that is what "meta" means. An agent that has never seen a Sparky
does not know what to do about a Sparky. So after the popularity ranking, any
card still unrepresented gets pulled in via the most popular deck that contains
it, and the shortfall is reported rather than hidden.

The output carries the same provenance contract as combat_rules.json and the
RoyaleAPI sync: source URL, SHA-256 of what was read, and the time it was read.

    python scripts/sync_meta_decks.py                 # default: top 200
    python scripts/sync_meta_decks.py --top 400
    python scripts/sync_meta_decks.py --check         # report drift, write nothing
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CARDS = ROOT / "data" / "royaleapi" / "cards.json"
OUT = ROOT / "data" / "meta_decks.json"

SOURCE = ("https://huggingface.co/datasets/raymond9326/clash-royale-battles"
          "/resolve/main/clash_royale_battles.csv")
SOURCE_PAGE = "https://huggingface.co/datasets/raymond9326/clash-royale-battles"

# Path of Legends is the competitive ladder, and it is the `battle_type`
# column - `game_mode` holds arena strings like "Ranked1v1_NewArena2". Other
# battle types in the log are 2v2, challenges and party modes, whose decks are
# not the ladder meta.
LADDER_TYPES = {"pathOfLegend"}

DECK_SIZE = 8
TIMEOUT = 120


def card_names() -> dict[str, str]:
    """Published card name -> the name this project plays it under.

    Joined on `sc_key`, the Supercell identifier, because that is what the
    loader derives its own names from. The obvious join - hyphens in the
    published `key` swapped for underscores - matches only 84 of 120: the
    published list says `archers` and `fire-spirit` where the client says
    `Archer` and `FireSpirits`. Through `sc_key` it is 119 of 120, the
    exception being Party Rocket, a party card the simulator does not play.
    """
    from sim.gamedata import to_snake_case
    from sim.deck_builder import playable_public_cards
    from sim.gamedata import load_gamedata
    from sim.spells import load_spells

    cards = load_gamedata(11)
    spells = load_spells(11)
    playable = set(playable_public_cards(cards, spells))
    # The published catalogue is stale - it carries 120 cards and none of the
    # 2026 additions - so a name is also matched straight against the client
    # table. Ronin is in about a tenth of ladder decks and is absent from
    # RoyaleAPI's list entirely; resolving only through that list silently
    # drops it and eight others the simulator already implements.
    known = set(cards) | set(spells)
    rows = json.loads(CARDS.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("cards", [])
    mapping: dict[str, str] = {}
    for row in rows:
        if not row.get("name"):
            continue
        for candidate in (to_snake_case(row.get("sc_key") or ""),
                          str(row.get("key", "")).replace("-", "_")):
            if candidate in playable:
                mapping[row["name"]] = candidate
                break
    return mapping, known


# Published names the client spells nothing like. Both of these were briefly
# mistaken for cards missing from the extracted data; both were there under a
# development codename that no case-mangling reaches.
#
#   Rune Giant     -> GiantBuffer, named for what it does to friendly troops
#   Spirit Empress -> MergeMaiden, whose two rows are her 3-elixir foot form
#                     and her 6-elixir mounted one
#
# She is a July 2025 card, so the guess that she postdated the extracted client
# was wrong by a year. When a published card looks absent, it is far more
# likely to be sitting under a codename than to be missing.
PUBLISHED_ALIASES = {
    "Rune Giant": "giant_buffer",
    "Spirit Empress": "merge_maiden__normal",
}


def resolve(name: str, catalogue: dict[str, str], known: set) -> str | None:
    """A published battle-log card name to the simulator's own key."""
    from sim.gamedata import to_snake_case
    if name in catalogue:
        return catalogue[name]
    aliased = PUBLISHED_ALIASES.get(name)
    if aliased and aliased in known:
        return aliased
    for candidate in (to_snake_case(name), name.lower().replace(" ", "_"),
                      name.lower().replace(" ", "").replace(".", "")):
        if candidate in known:
            return candidate
    return None


def stream_decks(limit_rows: int = 0):
    """Yield each ladder deck in the log as a sorted tuple of internal keys.

    Streamed rather than downloaded: the file is over half a gigabyte and only
    sixteen of its columns matter.
    """
    catalogue, known = card_names()
    digest = hashlib.sha256()
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "HastyCR sync"})
    unknown: Counter = Counter()
    rows_seen = 0

    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # nosec B310
        wrapper = io.TextIOWrapper(response, encoding="utf-8", errors="replace")
        reader = csv.DictReader(wrapper)
        for row in reader:
            rows_seen += 1
            digest.update(str(rows_seen).encode())
            if limit_rows and rows_seen > limit_rows:
                break
            if row.get("battle_type", "") not in LADDER_TYPES:
                continue
            for side in ("player", "opponent"):
                names = [row.get(f"{side}_card_{i}") for i in range(1, DECK_SIZE + 1)]
                if any(not name for name in names):
                    continue
                keys = []
                for name in names:
                    key = resolve(name, catalogue, known)
                    if key is None:
                        unknown[name] += 1
                        break
                    keys.append(key)
                if len(keys) == DECK_SIZE:
                    yield tuple(sorted(keys))

    stream_decks.rows_seen = rows_seen
    stream_decks.unknown = unknown
    stream_decks.digest = digest.hexdigest()


def build(top: int, limit_rows: int = 0) -> dict:
    counts: Counter = Counter()
    for deck in stream_decks(limit_rows):
        counts[deck] += 1

    ranked = counts.most_common()
    chosen = [list(deck) for deck, _ in ranked[:top]]
    usage = [count for _, count in ranked[:top]]

    # Coverage: every card the project can play should appear somewhere, so
    # the agent has at least seen it. Filled from the most popular deck that
    # contains each missing card.
    playable = set(card_names()[0].values())
    covered = {card for deck in chosen for card in deck}
    added_for_coverage = []
    for card in sorted(playable - covered):
        for deck, _count in ranked:
            if card in deck and list(deck) not in chosen:
                chosen.append(list(deck))
                usage.append(0)
                added_for_coverage.append(card)
                covered |= set(deck)
                break

    still_missing = sorted(playable - covered)
    seen_cards = sorted({card for deck in counts for card in deck})
    return {
        "schema": 1,
        "source": SOURCE_PAGE,
        "source_file": SOURCE,
        "source_license": "MIT",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows_read": getattr(stream_decks, "rows_seen", 0),
        "row_stream_sha256": getattr(stream_decks, "digest", ""),
        "battle_types": sorted(LADDER_TYPES),
        "distinct_decks_seen": len(counts),
        "top_requested": top,
        "decks": chosen,
        "usage_counts": usage,
        "added_for_coverage": added_for_coverage,
        # Every card observed in real Path of Legends play. This is the
        # evidence `sim.deck_builder` uses to decide a card is a ladder card,
        # because the published catalogue is stale by nine of them.
        "ladder_cards": seen_cards,
        "cards_never_seen": still_missing,
        "unknown_card_names": dict(getattr(stream_decks, "unknown", Counter())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=200)
    parser.add_argument("--rows", type=int, default=0,
                        help="stop after N log rows (for a quick check)")
    parser.add_argument("--check", action="store_true",
                        help="report what would change and write nothing")
    args = parser.parse_args()

    built = build(args.top, args.rows)
    print(f"read {built['rows_read']:,} battle rows")
    print(f"{built['distinct_decks_seen']:,} distinct ladder decks seen")
    print(f"keeping {len(built['decks'])} "
          f"({args.top} by usage + {len(built['added_for_coverage'])} for coverage)")
    if built["added_for_coverage"]:
        print(f"  pulled in to cover: {', '.join(built['added_for_coverage'])}")
    if built["cards_never_seen"]:
        print(f"  NOT COVERED ({len(built['cards_never_seen'])}): "
              f"{', '.join(built['cards_never_seen'])}")
    if built["unknown_card_names"]:
        top_unknown = sorted(built["unknown_card_names"].items(),
                             key=lambda kv: -kv[1])[:10]
        print(f"  card names not in cards.json: {top_unknown}")

    if args.check:
        print("--check: nothing written")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(built, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
