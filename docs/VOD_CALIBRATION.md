# Calibrating the simulator against recorded play

Built 2026-08-29. First results below.

## Why

Every constant in the engine was either decoded from the client's own tables,
which is trustworthy, or chosen by somebody, which is not. The chosen ones are
where it drifts from the real game, and the drift is not academic: measured
against one recorded match, an unblocked Hog Rider's seven tower hits reproduce
exactly, while a body-blocked one lands four in simulation against two in
reality.

That single gap explains why every policy trained here spams. In a world where
three Skeletons cost a Hog 0.6 seconds instead of five tower hits, throwing
cards at every threat is correct play. The agent learned it correctly; the
world was wrong.

One match gave one number. This pipeline does it at scale.

## The stages

    tools/vod/fetch.py      channel listing, one video at a time
    tools/vod/segment.py    spans that are matches, not menus
    tools/vod/track.py      detections to tile coordinates
    tools/vod/calibrate.py  observed behaviour vs the engine's constants
    tools/vod/pipeline.py   orchestration, resumable, deletes as it goes

Run it with:

    py -3.12 tools/vod/pipeline.py --videos 30 --streams 15
    py -3.12 tools/vod/calibrate.py --min-segments 5

### Two decisions worth knowing

**The pixel-to-tile transform is fitted per match, not hardcoded.** These are
phone recordings from different sessions and framing shifts between them. A
fixed mapping would bias every distance silently. Instead the crown towers -
whose tile positions are known exactly - are located by the detector and an
affine is fitted to them. The residual is reported, and a match whose fit
misses by more than 0.75 tiles is dropped rather than measured through. On real
footage the fit lands at 0.36 tiles.

**Segmentation keys on the arena, not the FIGHT! banner.** The banner is about
two seconds long, so a one-frame-per-second sweep misses it, and a rejoin never
shows one at all. Tower presence is steady at 0.9 confidence for a whole match.
The banner idea still applies where it matters: `refine_start` walks the
leading edge back at 0.2s steps, which is the precision elixir reasoning needs.

## First results

Ten matches, from eleven videos.

| card | n | observed | engine | difference |
|---|---|---|---|---|
| skeletons | 108 | 1.56 | 1.50 | **+4.0%** |
| dark_prince | 25 | 1.03 | 1.00 | **+3.1%** |
| hog_rider | 36 | 1.45 | 2.00 | **−27.4%** |
| musketeer | 9 | 1.20 | 1.00 | +20.1% (preliminary) |
| knight | 5 | 1.12 | 1.00 | +12.2% (preliminary) |
| prince | 5 | 2.17 | 1.00 | +116.9% (preliminary) |

Tiles per second. "Engine" is the speed the engine *steps a unit at*, not the
raw card value - those differ by 16.667x, and confusing them once produced a
report claiming the simulator was twenty times too slow.

### Reading it

**Two cards agree within 4%.** That is the important part, and it is a result
about the method as much as the engine: the transform, the tracker and the
sampling are accurate enough to reproduce a known constant. Without that, no
disagreement elsewhere would mean anything.

**The Hog Rider reads 27% slow at n=36.** With two other cards landing inside
4%, that is not noise. There are two candidate explanations and the data here
does not separate them:

1. The engine's Hog speed is wrong. Against this: the same 16.667x conversion
   that gives the Hog 2.00 gives Skeletons 1.50, and Skeletons check out at
   1.56. A broken conversion would miss on both.
2. **The observed Hog median is depressed by blocking.** The Hog is the most
   body-blocked card in the game, and a segment that is mostly-forward still
   passes the direction filter while being slowed. In other words the 27% may
   be the body-block effect itself, showing up in aggregate.

The second is more likely and is *consistent with the separate finding* that
the simulator under-models blocking: a real Hog spends much of its life being
slowed by bodies, a simulated one does not. If so, this number is corroboration
of the collision bug rather than a speed bug.

Separating them needs Hog segments filtered to those with no enemy unit within
a couple of tiles. That is the obvious next measurement and is not done yet.

**Prince at +117% is charging**, not a defect - the engine's base speed
excludes the charge multiplier. It is preliminary at n=5 and should be excluded
from the card map rather than read as a finding.

## Limits, stated so a number here is not read as more than it is

* Association is nearest-neighbour by class. Segments where same-class units
  come within 1.2 tiles are dropped rather than guessed, so crowded fights
  contribute nothing.
* Only consistently-forward segments are used. A unit that stopped to fight,
  got knocked back or was pulled has a speed that means something else.
* Nothing here sees a unit the detector misses, or any timing finer than the
  sampling interval.
* Under twenty clean segments, a row is labelled preliminary and should not be
  used for anything.

## Corpus status

Eleven of forty-five items processed before YouTube began requiring sign-in for
anonymous downloads - "Sign in to confirm you're not a bot", after roughly a
dozen fetches. The remaining items were **not attempted**; the manifest records
only genuine per-video failures, so a later run retries the rest rather than
skipping them.

Continuing needs either browser cookies passed to yt-dlp, or simply waiting for
the block to lapse. That is a decision for the repository owner, not something
to work around unattended.
