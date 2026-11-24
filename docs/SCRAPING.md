# Scraping replays of our deck (for an agent picking this up)

Written 2026-11-12. Everything here was run that day unless marked unverified.

## What to collect

Only this deck, from the top rated players of it on RoyaleAPI:

Evo Mortar, Hero Ice Wizard, Evo Skeleton Barrel, Cannon Cart, Fireball, Goblin
Gang, Rascals, Barbarian Barrel.

RoyaleAPI names decks by card form. Base names find nobody ("no rated players").
The slugs that work:

```
mortar-ev1,skeleton-barrel-ev1,cannon-cart,rascals,goblin-gang,fireball,barbarian-barrel,ice-wizard-hero
```

## The command

Run from `C:\Users\aksha\Downloads\HastyCR`. One command both starts and resumes:

```
.venvs\scraper\Scripts\python.exe tools\royale_scrape.py --deck "mortar-ev1,skeleton-barrel-ev1,cannon-cart,rascals,goblin-gang,fireball,barbarian-barrel,ice-wizard-hero" --out data\replays_mortar --players 80 --pages 3 --max-replays 100 --chunk 20 --ceiling 1 --workers 4 --challenge-wait 43200 --notify
```

- `--deck`: the eight slugs above. Battles played with any other deck are dropped
  ("dropped as a different deck" in the output).
- `--players 80`: the 80 highest rated players of this deck (the deck's ratings
  board; 242 are rated). This is the "top ladder" filter. `--pages 3` = their last
  30 battles each.
- `--out data\replays_mortar`: keep this folder for this deck only. Resuming
  depends on it.
- `--max-replays 100`: stop after 100 new replays. RoyaleAPI allows about that
  many a sitting.
- `--chunk 20`: replays are written to disk every 20. A stop loses at most the
  chunk in flight. (The default is 200, which with a 100 cap means nothing is
  saved until the end.)
- `--ceiling 1 --workers 4`: at most one request a second. At 4 a second the
  second sitting got 692 "too many requests" answers and stopped at 22 of 70.
  Unverified that 1 a second gets more through; it is the next thing to try.
- `--challenge-wait 43200 --notify`: see "When it needs a person".

## Resuming: it never starts over

Run the same command again with the same `--out`. The script does this itself:

1. `data\replays_mortar\pending_battles.json` holds every battle of the deck
   listed so far. A rerun loads it ("reusing N listed battles from a previous
   sitting") and adds only battles it has not seen.
2. `data\replays_mortar\battles.csv` holds every replay already downloaded. A
   rerun skips those tags ("N replays already on disk; skipping N of them, M new
   to fetch") and appends new rows to `battles.csv` and `plays.csv`. It never
   rewrites them.

So a stopped run costs only the chunk that was in flight, and a rerun cannot
produce duplicates. Do not delete or move those three files, and do not point
`--out` at a new folder, or it starts from nothing.

State on 2026-11-12: 52 replays downloaded, 330 more listed and waiting.

Check for duplicates any time:

```
.venvs\scraper\Scripts\python.exe -c "import csv;csv.field_size_limit(10**9);t=[r['replay_tag'] for r in csv.DictReader(open(r'data\replays_mortar\battles.csv',encoding='utf-8'))];print(len(t),len(set(t)))"
```

The two numbers must be equal.

## When it needs a person

The script opens a Chrome window with its own profile (`tmp\royale_loop_profile`).
The RoyaleAPI login and the Cloudflare pass are stored there, so the owner signs
in once, not per run. Do not delete that folder.

Cloudflare sometimes shows a "Verify you are human" checkbox, at the start or in
the middle of a run. Only the owner may tick it. With `--notify` the PC beeps and
shows a Windows message; with `--challenge-wait 43200` the run then waits up to
12 hours instead of ending, and carries on by itself once the box is ticked.

Do not restart the script while it is waiting. Every restart asks Cloudflare for
a new pass, and repeated restarts are what made it challenge every run in October.

## Rules

- Never click or script the checkbox, and never use an auto-clicker for it.
- Never use proxies, a VPS farm or extra RoyaleAPI accounts to get past the rate
  limit. The owner asked for both on 2026-11-12; both were refused. When RoyaleAPI
  answers "too many requests", stop for the day.
- One or two sittings a day. Whether the limit resets within a day is not known.

## Reading the output

- `battles.csv`: one row per replay. `battle_type` is `pathOfLegend` for ranked
  games (26 of the first 30); the rest are `clanMate` / `friendly`. Filter on that
  column when only ranked games are wanted. `result` is the listed player's.
  `team_deck` carries the forms.
- `plays.csv`: one row per card play: `replay_tag, tick, side, card, ability, x, y`.
  `tick` is 20 per second; `x, y` are arena units (18000 x 32000). A row with
  `ability` = 1 is a hero ability press: its `card` is `_invalid` and it has no
  position.
- Not written yet: a converter from these two files to the payload format
  `tools/league/engine_bc.py` reads (`data/il_replay`, schema
  `royaleapi-battle-actions.v1`). That is the next piece of work.

## If something breaks

- "no rated players for these N deck variations": the slugs are wrong (forms).
- Every replay answers 403 while other pages work: the Cloudflare pass is stale.
  The script refreshes it once a chunk comes back empty; if a checkbox shows, the
  owner ticks it.
- `IndexError` after "variations of the seed deck": fixed 2026-11-12 (it now
  prints the reason instead).
- The file's own header comment in `tools/royale_scrape.py` records the earlier
  wrong diagnoses; read it before changing the fetch code.
