Build a complete Clash Royale card-stats table for a Hog 2.6 bot's decision engine.

CRITICAL: your training data on Clash Royale is out of date, and this game rebalances
often. **Verify every number by web search** before writing it. Do NOT fetch
`clashroyale.fandom.com` — it returns HTTP 403 from this machine and a previous agent
wasted fifty minutes retrying it. Prefer search-result snippets and these sites, which
have worked: `statsroyale.com`, `royaleapi.com`, `deckshop.pro`, `clashroyale.com`.
Budget: at most 25 searches. If you cannot verify a number, use `null` — never a guess.

Write the result to exactly this path and nothing else:
  C:\Users\aksha\Downloads\HastyCR\scripts\brain\card_stats.json

Format: one JSON object mapping card name -> stats object. Use the SAME key names that
already appear in `C:\Users\aksha\Downloads\HastyCR\scripts\brain\units.json` — read that
file first and reuse its keys exactly. Do not rename, invent, or drop any.

Each value must be an object with EXACTLY these keys, at **tournament standard
(level 11)** unless the card is spawned-only:

  "cost":            integer elixir cost (0 for spawned-only units like skeleton, lava_pup)
  "hitpoints":       integer, per individual unit
  "damage":          integer per hit, per individual unit
  "dps":             integer damage per second, per individual unit
  "hit_speed":       number, seconds between attacks
  "range":           number in tiles; use 0 for melee
  "sight_range":     number in tiles (aggro range)
  "speed":           one of "slow" | "medium" | "fast" | "very fast"
  "speed_tiles_sec": number, movement in tiles per second
  "targets":         one of "ground" | "air_and_ground" | "buildings"
  "attack_type":     one of "single" | "splash" | "chain" | "none"
  "splash_radius":   number in tiles, 0 when not splash
  "count":           integer units deployed by the card
  "deploy_time":     number, seconds before the unit becomes active
  "mass":            one of "light" | "medium" | "heavy"  (push-back resistance)
  "role":            one of "win_condition" | "tank" | "mini_tank" | "support" |
                     "swarm" | "building" | "spell" | "spawner"
  "counters":        array of up to 5 card names (from the same key set) that beat it
                     cost-efficiently
  "countered_by_26": array of the subset of ["cannon","fireball","hog_rider","ice_golem",
                     "ice_spirit","musketeer","skeletons","the_log"] that answers it well

Rules:
- Output ONLY valid JSON. No markdown fences, no commentary, no trailing commas.
- Every key present in units.json must be present here.
- Do not modify any other file in the repository.
- Do not start, stop, or touch any bot process.

When done, print: CARD_STATS_DONE <number of keys written>
