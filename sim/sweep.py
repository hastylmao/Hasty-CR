"""Tune the bot's config by playing variants against the current baseline.

This is what the simulator is *for*. Live, one setting takes five matches and
twenty minutes to evaluate, and the result is swamped by opponent variance -
which is why the block reviews have been changing numbers largely on argument.
Here a setting is 200 matches against the exact same opponent in half a minute,
so the answer is a win rate rather than a plausible story.

    python -m sim.sweep --key cycle_to_hog_elixir --values 3 4 5 6 --matches 120

Each variant plays the **current** config, both sides mirrored, so the only
difference in the match is the setting under test.

Read the caveat before acting on the output: this measures what wins *in the
simulator*, and the simulator's procedures are approximations. A setting that
wins here is a candidate for a live block, not a conclusion.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

BASELINE = ROOT / "scripts" / "brain" / "config.json"


def freeze_baseline(directory: Path) -> Path:
    """Snapshot the config once, and compare everything against the snapshot.

    The live supervisor's review loop rewrites `scripts/brain/config.json`
    between blocks, so reading it per variant means racing a file that changes
    underneath the experiment. That showed up as every variant losing - even
    one set to the value the baseline already had, which scored 33% when it
    should have been a coin flip.
    """
    frozen = directory / "baseline.json"
    frozen.write_text(BASELINE.read_text(encoding="utf-8"), encoding="utf-8")
    return frozen


def variant_config(key: str, value, directory: Path, source: Path) -> Path:
    config = json.loads(source.read_text(encoding="utf-8"))
    if key in config:
        config[key] = value
    elif key in config.get("weights", {}):
        config["weights"][key] = value
    else:
        raise KeyError(f"{key} is not in config.json or its weights")
    path = directory / f"config_{key}_{value}.json"
    path.write_text(json.dumps(config, indent=1), encoding="utf-8")
    return path


def jittered_opponents(baseline: Path, directory: Path, spread: float,
                       count: int = 8, seed: int = 12345) -> List[Path]:
    """A pool of slightly-different opponents, instead of one fixed mirror.

    A sweep normally plays every variant against the *same* baseline config, so
    a setting can win by countering one predictable attacker rather than by
    being better. That is the most likely reason the largest simulator findings
    have not reproduced live: the ladder is not one opponent repeated 400 times.

    Perturbing the opponent's numeric settings by +/- `spread` gives a spread of
    behaviours at roughly the same strength. It does not make the opponent
    stronger - nothing here can - but it does stop a variant from being tuned to
    a single opponent's habits. The pool is fixed-seeded so runs stay comparable.
    """
    import random as _random

    source = json.loads(baseline.read_text(encoding="utf-8"))
    rng = _random.Random(seed)
    out: List[Path] = []
    for index in range(count):
        config = json.loads(json.dumps(source))
        for table in (config, config.get("weights", {})):
            for key, value in list(table.items()):
                if key.startswith("_") or isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    scale = 1.0 + rng.uniform(-spread, spread)
                    table[key] = (type(value))(value * scale) if not isinstance(value, bool) else value
        path = directory / f"opponent_{index}.json"
        path.write_text(json.dumps(config, indent=1), encoding="utf-8")
        out.append(path)
    return out


def evaluate(cards, spells, config_path: Path, matches: int, seed: int,
             baseline: Path = BASELINE, opponent: str = "brain",
             pool: Optional[List[Path]] = None) -> dict:
    """Play `config_path` against the baseline, alternating sides.

    Alternating matters: even with the decision order fixed, playing every
    match from the same side would fold any residual board asymmetry straight
    into the result.
    """
    from sim.runner import play_match

    wins = losses = draws = 0
    crowns_for = crowns_against = 0
    for index in range(matches):
        # Alternating sides cancels residual board asymmetry, but it only works
        # when both seats are config-driven. `play_match(opponent="simple")`
        # replaces the *top* player outright and ignores top_config, so
        # alternating would leave the variant unused in half the matches - which
        # is exactly how a sweep once returned an identical 199-201 for two
        # different settings. Against a non-brain opponent the variant always
        # takes the bottom seat; the asymmetry is then identical across
        # variants, so comparisons between them still hold.
        variant_on_bottom = True if opponent != "brain" else index % 2 == 0
        # With a pool, the opponent seat rotates through slightly different
        # configs so a variant cannot be tuned to one fixed attacker.
        other = pool[index % len(pool)] if pool else baseline
        match, _, _ = play_match(
            cards, seed=seed + index, spells=spells, opponent=opponent,
            bottom_config=config_path if variant_on_bottom else other,
            top_config=other if variant_on_bottom else config_path,
        )
        variant_side = 1 if variant_on_bottom else -1
        mine = match.crowns_for(variant_side)
        theirs = match.crowns_for(-variant_side)
        crowns_for += mine
        crowns_against += theirs
        won = (match.result == ("bottom" if variant_on_bottom else "top"))
        lost = (match.result == ("top" if variant_on_bottom else "bottom"))
        wins += won
        losses += lost
        draws += not (won or lost)
    decided = wins + losses
    return {
        "wins": wins, "losses": losses, "draws": draws,
        "crowns_for": crowns_for, "crowns_against": crowns_against,
        "win_rate": wins / decided if decided else 0.5,
        "crown_diff": crowns_for - crowns_against,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep one config setting")
    parser.add_argument("--key", required=True)
    parser.add_argument("--values", nargs="+", required=True)
    parser.add_argument("--matches", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--level", type=int, default=11)
    # Self-play is the default because a random opponent is not a test. But the
    # mirror defends exactly as well as we attack, which makes it a harsher
    # world for aggression than the ladder is; running a setting against both
    # says whether a conclusion depends on how good the opponent is.
    # "scripted" is the one worth using now: a mirror never punishes passivity,
    # which is why nothing measured here could price tempo. Real archetypes can.
    parser.add_argument("--opponent", choices=("brain", "simple", "scripted"),
                        default="brain")
    # Rotate the opponent seat through a pool of slightly perturbed configs so a
    # variant cannot win by countering one fixed, predictable attacker. 0 keeps
    # the old exact-mirror behaviour.
    parser.add_argument("--opponent-jitter", type=float, default=0.0,
                        metavar="SPREAD", help="e.g. 0.15 for +/-15%% opponent configs")
    args = parser.parse_args()

    from sim.gamedata import load_gamedata
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = resolve_deck(load_gamedata(level=args.level), DECK_26)
    spells = load_spells(level=args.level)

    def parse(text: str):
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return text

    print(f"sweeping {args.key} over {args.values}, "
          f"{args.matches} matches each against the current config\n")
    print(f"{'value':>10s} {'W':>4s} {'L':>4s} {'D':>4s} {'win%':>6s} {'crowns':>8s}")

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        frozen = freeze_baseline(directory)
        pool = (jittered_opponents(frozen, directory, args.opponent_jitter)
                if args.opponent_jitter > 0 else None)
        if pool:
            print(f"opponent pool: {len(pool)} configs at "
                  f"+/-{100 * args.opponent_jitter:.0f}%")
        for raw in args.values:
            value = parse(raw)
            path = variant_config(args.key, value, directory, frozen)
            stats = evaluate(cards, spells, path, args.matches, args.seed,
                             baseline=frozen, opponent=args.opponent, pool=pool)
            results.append((value, stats))
            print(f"{str(value):>10s} {stats['wins']:4d} {stats['losses']:4d} "
                  f"{stats['draws']:4d} {100 * stats['win_rate']:5.1f}% "
                  f"{stats['crowns_for']:>3d}-{stats['crowns_against']:<3d}")

    best = max(results, key=lambda item: (item[1]["win_rate"], item[1]["crown_diff"]))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = baseline.get(args.key, baseline.get("weights", {}).get(args.key))
    print(f"\nbest: {args.key} = {best[0]}  "
          f"({100 * best[1]['win_rate']:.1f}% vs current value {current})")
    # A coin flip over a few hundred matches is +/- a few points; anything
    # inside that is not a finding.
    if abs(best[1]["win_rate"] - 0.5) < 0.06:
        print("within noise - not enough evidence to change anything")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
