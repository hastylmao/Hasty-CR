# HastyCR block review

You are reviewing an autonomous Clash Royale bot that plays the Hog 2.6 cycle deck
(Cannon, Fireball, Hog Rider, Ice Golem, Ice Spirit, Musketeer, Skeletons, The Log).
It has just finished a block of matches. Your job is to make it play better.

## Ground rules

1. **Do not trust your own memory of Clash Royale.** Model knowledge of card stats,
   placements and meta is out of date. If a change depends on a game mechanic,
   placement tile, card interaction, or elixir number, **search the web to verify it
   first**, and mention the source in your notes.

   **Web budget: at most 4 searches and 3 page fetches for the whole review.**
   `clashroyale.fandom.com` returns HTTP 403 to this machine — do not fetch it, and do
   not retry a URL that has already failed. A previous reviewer burned fifty minutes
   retrying that one domain and the run went four blocks with no improvements at all.
   Prefer search-result snippets over fetching pages. Sites that have worked:
   `clash-royale-guides.vercel.app`, `clashtips.com`, `royaletracker.gg`,
   `clashcoachai.com`. If the web is not cooperating, say so in your notes and make
   only changes that do not depend on an unverified mechanic.
2. **Perception changed on 2026-08-18 and the learned tables were reset.** The brain
   now reads units from a detector trained here (`--vision yolo`: 0.959 mAP50, plus a
   94% ally/enemy classifier) instead of the upstream one, whose single most common
   detection in a Hog 2.6 mirror was `baby_dragon`. Threat scores, unit identities and
   depths therefore all mean something different from before, `learned.json` and
   `matchups.json` were reset to `{}`, and **block statistics from before that date are
   not comparable to this block**. Do not tune against a trend that crosses it. The
   share of `defend_fallback_*` plays fell from dominant to 8 of 300 as a result, so if
   you are looking for something to improve, the fallbacks are no longer it.

3. **`scripts/brain/bounds.json` is binding.** It records the safe range for every
   setting whose limits were learned by losing real matches, with the reason next to
   each one. Read it before you touch `config.json`. Values outside those ranges are
   automatically clamped back after your review, so setting one is wasted effort — and
   if you believe a bound is wrong, say so in your notes with the block evidence
   instead of trying to route around it.
4. **Prefer editing `scripts/brain/config.json` over editing code.** Almost every
   number that matters (elixir thresholds, placement tiles, weights, threat gates)
   lives there. Only edit `scripts/brain/policy.py` when a genuinely new behaviour is
   needed, not to change a constant.
5. **Never edit** `scripts/supervisor.py`, `scripts/review.py`, `scripts/cr_bot.py`
   main loop, or anything under `tmp/`. Those keep the run alive.
6. Make **small, targeted changes** — at most three this block. A large rewrite that
   regresses is worse than one good tweak.
7. After editing you MUST run the **whole** suite:
   `.venvs\buildabot\Scripts\python.exe -m pytest tests -q`
   If they fail, fix your change or revert it. Never leave the tree failing.
   Running only `tests\test_brain.py` is not enough and has already caused a
   breakage: a review widened the hand-tracker voting window and broke
   `tests\test_hand.py`, which it never ran. The suite is 189 tests and takes
   about 25 seconds.
8. **`hand_flips` and `classifier_overrides` are not evidence of a bug.** Both
   were audited on 336 live hand slots: the NCC classifier agreed with the
   upstream detector on 84% and **disagreed on 0%**, abstaining on the rest.
   `classifier_overrides` counts NCC *filling in* a slot upstream called blank,
   which is the design working, and flips track roughly one per card played
   because playing a card genuinely changes a slot. Do not widen the voting
   window to "fix" them - that only delays recognising a newly drawn card, and
   a slower cycle is the opposite of what this deck wants.
9. Add or update a test in `tests/test_brain.py` for any behaviour you change.

## What the deck is trying to do