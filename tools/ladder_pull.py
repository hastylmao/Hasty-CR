"""What top ladder is actually playing, from Supercell's own API.

Every policy this project has trained comes out strong against whatever it was
selected on and weaker against the rest. The last run held out at 93.5% against
the rule engine and 78.0% against meta decks, on a training diet that is half
rule engine and a hand-picked list of meta decks. This is where a real
opponent pool comes from: the Path of Legends leaderboard, then each of those
players' recent ranked battles, then the deck distribution that falls out.

Why this and not `tools/royale_scrape.py`: RoyaleAPI's replay endpoint is
blocked (see that module), its crawl needs a person to clear a checkbox, and
one sitting yielded 1,467 battles in twenty minutes. This is sanctioned, needs
no browser, and returns roughly thirty battles for every player on the
leaderboard. What it cannot give is the card-by-card timeline - the official
API exposes decks and results, not replays.

    python tools/ladder_pull.py --top 1000

The token is read from `.secrets/supercell_token`, which is gitignored. Keys
are bound to a single public IP, so a changed address fails every request with
`accessDenied.invalidIp` and the fix is to edit the key rather than the code.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / ".secrets" / "supercell_token"
BASE = "https://api.clashroyale.com/v1"

# Ranked ladder only. A battlelog also carries challenges, 2v2 and friendlies,
# and none of those are the metagame this bot plays in.
RANKED_TYPES = {"pathOfLegend", "pathOfLegendMatch"}


class Rate:
    """A simple ceiling on requests per second, shared across threads.

    The developer tier is throttled and the documented limit is not published
    as a number, so this stays well under anything plausible rather than
    probing for it. The whole point of using the official API is not having to
    find out where somebody's limiter gives up.
    """

    def __init__(self, per_second: float):
        self.gap = 1.0 / max(0.1, per_second)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            due = max(now, self._next)
            self._next = due + self.gap
        if due > now:
            time.sleep(due - now)


def get(path: str, token: str, rate: Rate, scratch: Path) -> dict | list | None:
    """One GET, forced over IPv4 because the key is bound to an IPv4 address."""
    rate.wait()
    out = scratch / f"resp_{threading.get_ident()}.json"
    argv = ["curl", "-4", "-sS", "--compressed", "--max-time", "30",
            "-o", str(out), "-w", "%{http_code}",
            "-H", f"Authorization: Bearer {token}", f"{BASE}/{path}"]
    done = subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    code = (done.stdout or "").strip()
    if code != "200":
        if code == "403":
            raise SystemExit(
                "403 from the API. The key is bound to one public IP and this "
                "machine's has probably changed; the response body names the "
                "address it saw. Edit the key at developer.clashroyale.com "
                "rather than making a new one.")
        return None
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def leaderboard(token: str, rate: Rate, scratch: Path, want: int) -> list[dict]:
    """The Path of Legends global top, paged until `want` players."""
    players: list[dict] = []
    after = None
    while len(players) < want:
        page = min(1000, want - len(players))
        path = f"locations/global/pathoflegend/players?limit={page}"
        if after:
            path += f"&after={after}"
        data = get(path, token, rate, scratch)
        if not isinstance(data, dict) or not data.get("items"):
            break
        players.extend(data["items"])
        after = data.get("paging", {}).get("cursors", {}).get("after")
        if not after:
            break
    return players[:want]


def battles_for(tag: str, token: str, rate: Rate, scratch: Path) -> list[dict]:
    data = get(f"players/{quote(tag)}/battlelog", token, rate, scratch)
    return data if isinstance(data, list) else []


def deck_of(side: dict) -> str:
    """A deck as a stable, comparable string: card names, sorted.

    The card's form rides along as a suffix: "Cannon*evo" for evolutionLevel 1,
    "Musketeer*hero" for 2 (the API's own encoding: in the 2026-09 pull, every
    Berserker, Mega Minion and Magic Archer at level 2 is a hero card). Without
    it every opponent deck trained as base cards.
    """
    form = {1: "*evo", 2: "*hero"}
    return ",".join(sorted(c["name"] + form.get(c.get("evolutionLevel") or 0, "")
                           for c in side.get("cards", [])))


def rows_from(battle: dict, elo: dict) -> list[dict]:
    """One row per battle. Both sides are recorded, so either can be the meta.

    A battle between two ranked players appears in both of their logs, so the
    caller dedupes on the key returned here.
    """
    if battle.get("type") not in RANKED_TYPES:
        return []
    team, opp = battle.get("team") or [], battle.get("opponent") or []
    if len(team) != 1 or len(opp) != 1:
        return []                       # 2v2, not this metagame
    t, o = team[0], opp[0]
    return [{
        "battle_time": battle.get("battleTime", ""),
        "player_tag": t.get("tag", ""),
        "opponent_tag": o.get("tag", ""),
        "player_deck": deck_of(t),
        "opponent_deck": deck_of(o),
        "player_crowns": t.get("crowns", 0),
        "opponent_crowns": o.get("crowns", 0),
        "player_elo": elo.get(t.get("tag", ""), ""),
        "opponent_elo": elo.get(o.get("tag", ""), ""),
    }]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=1000,
                    help="how many Path of Legends players to walk")
    ap.add_argument("--rate", type=float, default=5.0,
                    help="requests per second ceiling, kept deliberately low")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "ladder")
    args = ap.parse_args()

    if not TOKEN_FILE.exists():
        raise SystemExit(f"no token at {TOKEN_FILE}")
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    scratch = args.out / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    rate = Rate(args.rate)

    started = time.time()
    players = leaderboard(token, rate, scratch, args.top)
    if not players:
        raise SystemExit("the leaderboard came back empty")
    elo = {p["tag"]: p.get("eloRating", "") for p in players}
    print(f"{len(players):,} players, elo {players[0].get('eloRating')} down to "
          f"{players[-1].get('eloRating')}")

    rows: dict = {}
    done = [0]

    def walk(player):
        for battle in battles_for(player["tag"], token, rate, scratch):
            for row in rows_from(battle, elo):
                # The same battle is in both players' logs; key it so it lands
                # once regardless of whose log it came from.
                key = (row["battle_time"],
                       *sorted((row["player_tag"], row["opponent_tag"])))
                rows.setdefault(key, row)
        done[0] += 1
        if done[0] % 100 == 0:
            print(f"  {done[0]:,}/{len(players):,} players, "
                  f"{len(rows):,} battles", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(walk, players))

    args.out.mkdir(parents=True, exist_ok=True)
    battles_csv = args.out / "ladder_battles.csv"
    fields = list(next(iter(rows.values())))
    with battles_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        writer.writerows(rows.values())

    # The metagame: how often each deck appears on either side.
    seen = collections.Counter()
    wins = collections.Counter()
    for row in rows.values():
        for me, them, mine, theirs in (
                ("player_deck", "opponent_deck", "player_crowns", "opponent_crowns"),
                ("opponent_deck", "player_deck", "opponent_crowns", "player_crowns")):
            seen[row[me]] += 1
            if row[mine] > row[theirs]:
                wins[row[me]] += 1
    meta = [{"deck": d, "seen": n, "wins": wins[d],
             "win_rate": round(wins[d] / n, 3), "share": round(n / sum(seen.values()), 5)}
            for d, n in seen.most_common()]
    (args.out / "ladder_meta.json").write_text(
        json.dumps(meta, indent=1), encoding="utf-8")

    elapsed = time.time() - started
    print(f"\n{len(rows):,} ranked battles from {len(players):,} players "
          f"in {elapsed / 60:.1f} min")
    print(f"{len(meta):,} distinct decks")
    print(f"  {battles_csv}")
    print(f"  {args.out / 'ladder_meta.json'}")
    print("\nmost played decks at top ladder:")
    for entry in meta[:10]:
        print(f"  {entry['share']:>6.2%}  {entry['win_rate']:>5.0%}  "
              f"{entry['deck'][:78]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
