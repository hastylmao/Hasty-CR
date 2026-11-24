"""Which cards go with re-drives that leave the real game? (2026-11-15)

    redrive_cards.py runs/league/uc_diag/diag_tags.jsonl runs/league/uc_diag/diag_tags.log

redrive_diag.py writes one record per game (stop reason) and prints each game's two
decks to stderr. A game whose engine re-drive ends before the real one did
("engine_game_over_early") holds at least one thing the engine runs differently from
the real game. This ranks cards by how much more often their games end early than
games without them. It is a pointer for where to look, not proof: cards travel in decks
together and 200 games give wide intervals.
"""
import ast
import collections
import json
import sys

recs = {r["game"]: r for r in map(json.loads, open(sys.argv[1]))}
decks = {}
for line in open(sys.argv[2], errors="replace"):
    if line.startswith("game "):
        n, rest = line[5:].split(" ", 1)
        try:
            decks[int(n)] = ast.literal_eval(rest.strip())
        except (ValueError, SyntaxError):
            pass
games = [g for g in recs if g in decks and recs[g]["stop"] in ("none", "engine_game_over_early")]
bad = {g for g in games if recs[g]["stop"] == "engine_game_over_early"}
has = collections.defaultdict(set)
for g in games:
    for c in set(decks[g][0]) | set(decks[g][1]):
        has[c].add(g)
base = len(bad) / max(1, len(games))
print(f"{len(games)} games, {len(bad)} end early ({base:.0%})")
rows = []
for c, gs in has.items():
    if len(gs) < 6:
        continue
    w = len(gs & bad)
    wo = (len(bad) - w) / max(1, len(games) - len(gs))
    rows.append((w / len(gs) - wo, c, len(gs), w, wo))
for lift, c, n, w, wo in sorted(rows, reverse=True)[:25]:
    print(f"{c:34s} {w:3d} of {n:3d} early ({w / n:4.0%})   without it {wo:4.0%}")
