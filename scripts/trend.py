"""Cross-block progress curve.

Per-block review can't tell improvement from noise. This reads every block log
and reports the trend in the numbers that decide matches: crowns taken vs
conceded, and how often the win condition actually reached a tower.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RESULT = re.compile(r"MATCH_RESULT .*match_actions=(\d+) .*duration=(\d+) .*towers=(\S+)")
# A match that ends very fast with almost no cards played is an opponent who
# quit, not a win the bot earned. Counting those inflates the crown rate.
WALKOVER_SECONDS = 70
WALKOVER_ACTIONS = 6
PLAY = re.compile(r"PLAY #\d+ (\w+)")
SHIM = re.compile(r"SHIM (\w+?)(?:_lane\d+|\(|\s|$)")


def block_stats(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    ours_lost = theirs_lost = matches = walkovers = walkover_crowns = 0
    for match in RESULT.finditer(text):
        actions, duration, towers = int(match.group(1)), int(match.group(2)), match.group(3)
        if "-" not in towers or "?" in towers:
            continue
        ours, theirs = towers.split("-")
        try:
            ours_hp = [float(v) for v in ours.split("/")]
            theirs_hp = [float(v) for v in theirs.split("/")]
        except ValueError:
            continue
        matches += 1
        crowns = sum(1 for v in theirs_hp if v <= 0.0)
        ours_lost += sum(1 for v in ours_hp if v <= 0.0)
        theirs_lost += crowns
        if duration < WALKOVER_SECONDS and actions <= WALKOVER_ACTIONS:
            walkovers += 1
            walkover_crowns += crowns
    plays = PLAY.findall(text)
    shims = SHIM.findall(text)
    return {
        "matches": matches,
        "crowns_for": theirs_lost,
        "crowns_against": ours_lost,
        "plays": len(plays),
        "hog": plays.count("hog_rider"),
        "shims": len(shims),
        "walkovers": walkovers,
        "walkover_crowns": walkover_crowns,
    }


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "tmp/live/blocks")
    logs = sorted(root.glob("block_*.log"))
    print(
        f"{'block':<7}{'matches':>8}{'crowns+':>9}{'earned':>8}{'crowns-':>9}"
        f"{'plays':>7}{'hog%':>7}{'shims':>7}"
    )
    tot_for = tot_against = tot_walk = tot_walk_crowns = 0
    for log in logs:
        s = block_stats(log)
        if not s["matches"]:
            continue
        tot_for += s["crowns_for"]
        tot_against += s["crowns_against"]
        tot_walk += s["walkovers"]
        tot_walk_crowns += s["walkover_crowns"]
        hog_pct = 100 * s["hog"] / s["plays"] if s["plays"] else 0
        earned_block = s["crowns_for"] - s["walkover_crowns"]
        print(
            f"{log.stem.replace('block_',''):<7}{s['matches']:>8}{s['crowns_for']:>9}"
            f"{earned_block:>8}{s['crowns_against']:>9}{s['plays']:>7}"
            f"{hog_pct:>6.1f}%{s['shims']:>7}"
        )
    print(f"\ntotal crowns for={tot_for} against={tot_against} ratio={tot_for / max(1, tot_against):.2f}")
    print(
        "WARNING: EVERY crown column above is UNRELIABLE and kept only for continuity.\n"
        "  `towers=` on MATCH_RESULT is read from the last in-game frame, which lands during\n"
        "  the end-of-match sequence when HP bars vanish, so a tower reads 0.00 whether or not\n"
        "  it actually fell. Verified 2026-08-16 11:10: a match logged as enemy 0.00/0.00\n"
        "  (scored here as 2 crowns for us) was a 3-0 LOSS on the result screen.\n"
        "  Use scripts/results.py for real outcomes. Mid-match PLAY-line HP is fine, so\n"
        "  scripts/conversion.py remains valid."
    )
    if tot_walk:
        earned = tot_for - tot_walk_crowns
        print(
            f"of those, {tot_walk_crowns} crowns came from {tot_walk} likely walkovers "
            f"(<{WALKOVER_SECONDS}s and <={WALKOVER_ACTIONS} cards) -> earned crowns = {earned}"
        )

    # Does playing the win condition more actually correlate with crowns?
    # If this is near zero, pushing hog share harder is not the lever.
    pairs = []
    for log in logs:
        s = block_stats(log)
        if s["matches"] and s["plays"]:
            pairs.append((100 * s["hog"] / s["plays"], s["crowns_for"] - s["walkover_crowns"]))
    if len(pairs) >= 5:
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in pairs)
        vx = sum((x - mx) ** 2 for x in xs) ** 0.5
        vy = sum((y - my) ** 2 for y in ys) ** 0.5
        r = cov / (vx * vy) if vx and vy else 0.0
        print(
            f"hog% vs earned crowns: r = {r:+.2f} over {len(pairs)} blocks "
            f"(|r| < 0.4 here means no usable signal)"
        )

    # Crowns are a low-rate count: with ~0.7 per 5-match block, a run of zeros
    # is ordinary and a single 4 is not a breakthrough. Comparing two configs
    # over a handful of blocks each will mislead you, so state the uncertainty.
    blocks = sum(1 for log in logs if block_stats(log)["matches"])
    if blocks:
        rate = tot_for / blocks
        stderr = (tot_for ** 0.5) / blocks          # Poisson count error
        low, high = max(0.0, rate - 1.96 * stderr), rate + 1.96 * stderr
        print(
            f"crowns-for per block = {rate:.2f}  (95% CI {low:.2f}-{high:.2f}, {blocks} blocks)"
        )
        if rate > 0:
            # Blocks needed to distinguish a 50% improvement from this baseline.
            needed = int(round((2 * 1.96 / 0.5) ** 2 / max(rate, 0.01)))
            print(
                f"to call a 50% improvement real you need ~{needed} blocks per config "
                f"({needed * 5} matches) - anything less is noise"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
