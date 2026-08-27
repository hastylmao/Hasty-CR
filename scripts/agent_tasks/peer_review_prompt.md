You are peer-reviewing a newly written Clash Royale bot decision engine. Be adversarial
and concrete. This code drives a live emulator unattended for two days, so a silent
logic bug costs hundreds of matches.

Read these files:
  scripts/brain/policy.py
  scripts/brain/arena.py
  scripts/brain/tracker.py
  scripts/brain/knowledge.py
  scripts/brain/config.json
  scripts/cr_bot.py
  tests/test_brain.py

The deck is Hog 2.6: Cannon, Fireball, Hog Rider, Ice Golem, Ice Spirit, Musketeer,
Skeletons, The Log. The grid is 18 wide x 32 tall, top-down y, y<16 is the enemy half,
y>=16 is ours, our princess towers sit at (4,24) and (14,24).

IMPORTANT: your Clash Royale knowledge is probably out of date. Use web search before
claiming any placement, elixir cost, card interaction or mechanic is wrong.

Look specifically for:
1. Correctness bugs: coordinate sign errors, off-by-one in slot indices (state.cards is
   [next, hand1..hand4] and state.ready holds 0-based hand slots), unreachable branches,
   candidates that can never be legal, state that is never reset between matches.
2. Strategy errors versus real 2.6 play: wrong placements, wrong elixir thresholds,
   cards used for the wrong job, Hog Rider being under-played (it should be 15-25% of
   all cards played and it is currently far below that).
3. Anything that could throw an unhandled exception in the live loop.
4. Anything that would make the bot spend elixir on nothing.

DO NOT EDIT ANY FILE. This is review only - another process is actively running this
code and editing it underneath you would corrupt a live run.

Write your review to scripts/agent_tasks/peer_review_kimi.md as a numbered list, each
item with: severity (high/medium/low), file and line, the concrete failure it causes,
and the specific fix you recommend. Rank by severity. Maximum 15 items - only real
findings, no style commentary. Then print PEER_REVIEW_DONE.
