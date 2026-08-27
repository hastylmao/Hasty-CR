"""What the bot's record actually is, and whether a change moved it.

Written because the same throwaway analysis kept being retyped, and because the
interesting question is never "what is the record" but "what is the record since
the thing I changed". Change times are appended to `tmp/live/change_markers.txt`
by hand or by a script; every marker becomes a split point.

    python scripts/record.py                 # all-time, plus each marker window
    python scripts/record.py --hours 6       # just the last 6 hours
    python scripts/record.py --since "2026-08-18 00:43"

Crowns come from the tower fractions recorded at MATCH_END: a lane at 0.00 is a
crown. That is reliable for *dead* towers - a fallen tower reads zero either way -
which is why this counts crowns rather than trying to use the fractions
themselves, whose absolute values `scripts/results.py` documents as unreliable.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, NamedTuple, Optional

ROOT = Path(__file__).resolve().parents[1]
MATCHES = ROOT / "tmp" / "live" / "matches"
MARKERS = ROOT / "tmp" / "live" / "change_markers.txt"
LOG = ROOT / "tmp" / "live" / "cr_bot.log"

TOWERS = re.compile(r"([\d.]+)/([\d.]+)-([\d.]+)/([\d.]+)")
DEAD = 0.001


class Match(NamedTuple):
    at: datetime
    for_crowns: int
    against: int
    plays: int
    hog: int
    seconds: int

    @property
    def outcome(self) -> str:
        if self.for_crowns > self.against:
            return "win"
        return "loss" if self.against > self.for_crowns else "draw"


def load() -> List[Match]:
    out: List[Match] = []
    for path in sorted(MATCHES.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        ended, towers = record.get("ended_at"), record.get("towers") or ""
        match = TOWERS.match(towers)
        if not ended or not match:
            continue
        ally_left, ally_right, enemy_left, enemy_right = (float(v) for v in match.groups())
        out.append(Match(
            at=datetime.fromisoformat(ended),
            for_crowns=(enemy_left <= DEAD) + (enemy_right <= DEAD),
            against=(ally_left <= DEAD) + (ally_right <= DEAD),
            plays=int(record.get("plays") or 0),
            hog=int((record.get("play_counts") or {}).get("hog_rider", 0)),
            seconds=int(record.get("duration_s") or 0),
        ))
    return out


def summarise(label: str, rows: List[Match]) -> None:
    if not rows:
        print(f"  {label:<34s} (no matches)")
        return
    n = len(rows)
    wins = sum(r.outcome == "win" for r in rows)
    losses = sum(r.outcome == "loss" for r in rows)
    draws = n - wins - losses
    plays = sum(r.plays for r in rows)
    hog = sum(r.hog for r in rows)
    took = sum(r.for_crowns > 0 for r in rows)
    conceded = sum(r.against > 0 for r in rows)
    print(f"  {label:<34s} n={n:<4d} W{wins} L{losses} D{draws}   "
          f"crowns {sum(r.for_crowns for r in rows)}-{sum(r.against for r in rows)} "
          f"({sum(r.for_crowns for r in rows)/n:.2f}-{sum(r.against for r in rows)/n:.2f})   "
          f"hog {100*hog/max(1,plays):4.1f}%   "
          f"took {100*took/n:3.0f}%  conceded {100*conceded/n:3.0f}%   "
          f"{sum(r.seconds for r in rows)/n:.0f}s")


def skipped_matches(cutoff: Optional[datetime] = None) -> List[tuple]:
    """Battles the bot entered but never registered, so they have no record.

    `battle_guard` can reject every frame of a live match. When it does, no
    MATCH_START fires, no MATCH_END is written, and the match is absent from
    tmp/live/matches entirely - which means every win rate computed from those
    files silently excludes a game the bot lost without playing a card. Nine of
    them happened in six hours. They belong in the report even though there is
    no file for them.
    """
    if not LOG.exists():
        return []
    events = []
    for raw in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (SCREEN|MATCH_START)(.*)", raw)
        if match:
            events.append((datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"),
                           match.group(2), match.group(3).strip()))
    out, entered = [], None
    for when, kind, rest in events:
        if kind == "SCREEN" and rest.endswith("->in_game"):
            entered = when
        elif kind == "MATCH_START":
            entered = None
        elif kind == "SCREEN" and entered and rest.startswith("in_game->"):
            seconds = (when - entered).total_seconds()
            if seconds >= 20 and (cutoff is None or entered >= cutoff):
                out.append((entered, seconds))
            entered = None
    return out


def markers() -> List[tuple]:
    if not MARKERS.exists():
        return []
    out = []
    for line in MARKERS.read_text(encoding="utf-8").splitlines():
        stamp = line[:19].strip()
        try:
            out.append((datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S"), line[19:].strip()))
        except ValueError:
            continue
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Report the bot's record")
    parser.add_argument("--hours", type=float, help="only the last N hours")
    parser.add_argument("--since", help="only after this 'YYYY-MM-DD HH:MM' time")
    parser.add_argument("--no-markers", action="store_true")
    args = parser.parse_args()

    rows = load()
    if not rows:
        print("no match records under tmp/live/matches")
        return 1

    cutoff: Optional[datetime] = None
    if args.hours:
        cutoff = datetime.now() - timedelta(hours=args.hours)
    if args.since:
        cutoff = datetime.fromisoformat(args.since)
    if cutoff:
        rows = [r for r in rows if r.at >= cutoff]

    print(f"{len(rows)} matches, {rows[0].at:%Y-%m-%d %H:%M} to {rows[-1].at:%H:%M}\n")
    print("legend: took/conceded = share of matches with at least one crown either way\n")
    summarise("all", rows)
    summarise("last 20", rows[-20:])

    lost = skipped_matches(cutoff)
    if lost:
        wasted = sum(seconds for _, seconds in lost)
        print()
        print(f"  {len(lost)} match(es) entered but never started - no record "
              f"exists for these, and the bot played no card in them, so treat "
              f"them as losses the table above is missing "
              f"({wasted / 60:.1f} min of dead play).")
        for when, seconds in lost[-5:]:
            print(f"    {when:%H:%M:%S}  {seconds:.0f}s")

    if not args.no_markers:
        found = markers()
        if found:
            print("\naround each recorded change:")
            for when, what in found:
                before = [r for r in rows if r.at < when]
                after = [r for r in rows if r.at >= when]
                print(f"\n  {when:%H:%M}  {what}")
                summarise("before", before[-40:])
                summarise("after", after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
