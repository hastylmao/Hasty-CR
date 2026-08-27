"""Sweep many settings unattended and write down what the numbers said.

One sweep answers one question in about a minute. Left running for a few hours
this works through the whole tunable surface, which is not something the live
loop could ever do: live, each setting costs five matches and twenty minutes
and the answer is swamped by opponent variance.

Results go to `tmp/live/campaign.md` as they arrive, so a run that is
interrupted still leaves everything it had learned.

    python -m sim.campaign --matches 160

Nothing here edits `config.json`. A campaign produces evidence; applying it is
a separate, deliberate step - partly because the simulator's procedures are
approximations, and partly because an automated tuner that edits the live bot
while it plays is how you end up unable to explain your own results.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

REPORT = ROOT / "tmp" / "live" / "campaign.md"

# Ordered by how much is unknown about them. The scoring weights are the least
# explored part of the config: every one was set by hand from an argument.
# Defence first, and every range brackets the value currently in config.json so
# the first arm doubles as a control - a sweep whose control is not near 50% is
# measuring the harness, not the setting.
#
# Two reasons this list is aimed at defence rather than at the Hog. Measured over
# 34 live matches, the bot takes a tower in 62% of them and concedes one in 82%,
# and 53% of all matches end 1-1: offence is no longer the binding constraint.
# And every defensive number here was last swept *before* the spell-placement fix,
# so it was measured with Fireball and Log unable to reach anything on the enemy
# half - which is half of defending into a counter-push.
#
# Offence entries were dropped: the simulator over-rewards defence (its only
# opponents are an exact mirror and a bot it beats 99.7% of the time), so it is
# the wrong instrument for "should we attack more" and a fine one for "which
# defence trades better". See docs/RUN_JOURNAL.md.
PLAN = [
    ("defend_elixir_ratio", [2.0, 1.8, 2.4]),
    ("defend_min_budget", [6.0, 8.0, 10.0]),
    ("defend_max_cards_per_push", [5, 3, 6]),
    ("defend_threat_to_elixir", [0.5, 0.35, 0.7]),
    ("threat_per_extra_card", [6, 10, 14]),
    ("reserve_elixir_when_threatened", [3, 2, 5]),
    ("contained_defence_penalty", [-80.0, -50.0, -25.0]),
    ("threat_scale", [1.5, 1.0, 2.2]),
    ("defend_min_threat", [4.0, 3.5, 5.0]),
    ("kite_min_threat", [6, 4, 8]),
    ("predict_seconds", [1.4, 2.0, 2.6]),
    ("emergency_depth", [23, 19, 21]),
    ("defend_cannon", [58.0, 45.0, 70.0]),
    ("defend_kite", [55.0, 40.0, 70.0]),
    ("defend_air", [62.0, 50.0, 62.0]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep many settings unattended")
    parser.add_argument("--matches", type=int, default=160)
    parser.add_argument("--seed", type=int, default=90000)
    parser.add_argument("--level", type=int, default=11)
    args = parser.parse_args()

    from sim.gamedata import load_gamedata
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells
    from sim.sweep import evaluate, freeze_baseline, variant_config

    cards = resolve_deck(load_gamedata(level=args.level), DECK_26)
    spells = load_spells(level=args.level)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as report:
        report.write(f"\n\n# Campaign {time.strftime('%Y-%m-%d %H:%M')} "
                     f"({args.matches} matches per value)\n\n")
        report.flush()

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            frozen = freeze_baseline(directory)
            baseline_values = json.loads(frozen.read_text(encoding="utf-8"))

            # The null case, and the reference point for everything after it.
            #
            # Every value is played on the *same* seed set, which is what makes
            # this a paired comparison - but it also means any bias in that
            # particular set of matches shifts every absolute win rate
            # together. The first run of this campaign showed exactly that: the
            # control came out at 42.1%, not because the harness was broken but
            # because those 140 seeds happened to favour the top side. So the
            # number that matters is each variant's win rate **relative to the
            # control**, where the shared bias cancels out.
            control = evaluate(cards, spells, frozen, args.matches, args.seed,
                               baseline=frozen)
            control_rate = control["win_rate"]
            line = (f"**control (baseline vs itself): {100 * control_rate:.1f}%** - "
                    f"the same seeds are used throughout, so read the `delta` "
                    f"column, not the raw win rate.\n\n")
            print(line.strip())
            report.write(line)
            report.write("| setting | value | W | L | D | win% | delta | crowns |\n")
            report.write("|---|---|---|---|---|---|---|---|\n")
            report.flush()

            for key, values in PLAN:
                current = baseline_values.get(
                    key, baseline_values.get("weights", {}).get(key))
                # Record the frozen baseline value alongside the results. The
                # live review loop rewrites config.json between blocks, so the
                # value a campaign is comparing against is whatever happened to
                # be there when it started - not necessarily what you last set.
                # Without this line a -7.1 delta looks like a finding when it is
                # really a variant being compared to a value you did not expect.
                print(f"\n== {key} (frozen baseline {current})")
                report.write(f"| _{key}_ | _baseline {current}_ | | | | | | |\n")
                report.flush()
                for value in values:
                    try:
                        path = variant_config(key, value, directory, frozen)
                    except KeyError:
                        print(f"   {key} not in config; skipped")
                        break
                    started = time.monotonic()
                    stats = evaluate(cards, spells, path, args.matches,
                                     args.seed, baseline=frozen)
                    delta = 100 * (stats["win_rate"] - control_rate)
                    # Roughly two sigma on this sample size; below that a
                    # difference is not worth acting on.
                    mark = " **" if delta >= 8.0 else ""
                    print(f"   {str(value):>8s}  {100 * stats['win_rate']:5.1f}%  "
                          f"delta {delta:+5.1f}  "
                          f"crowns {stats['crowns_for']}-{stats['crowns_against']}  "
                          f"({time.monotonic() - started:.0f}s)")
                    report.write(
                        f"| {key} | {value} | {stats['wins']} | {stats['losses']} | "
                        f"{stats['draws']} | {100 * stats['win_rate']:.1f}% | "
                        f"{delta:+.1f}{mark} | "
                        f"{stats['crowns_for']}-{stats['crowns_against']} |\n")
                    report.flush()

    print(f"\nwritten to {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
