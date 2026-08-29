"""Score a policy by where it puts cards, not by whether it wins.

Every win rate this project has produced has been misleading. The checkpoint
that beats the rule engine 93.3% in simulation lost 3-0 to a person; the clone
that manages 16.7% is the one pushing trophies on ladder. Selection has been
running on a number anti-correlated with the thing it is supposed to predict.

Placement is a second opinion that the simulator cannot fake, because the
reference comes from outside it: `tools/vod/plays.py` measures where a strong
player actually puts each card, from recorded ladder footage. A policy can be
compared against that without anyone winning anything.

Two numbers per card:

    offset   how far the policy's median placement sits from the pro median,
             in tiles. Large means it plays the card somewhere else entirely.
    spread   the policy's positional variation over the pro's. Around 1.0 means
             it adapts placement like a person does; well under 1.0 means it
             drops the card in the same spot regardless of the board, which is
             what our live logs show and what a win rate never revealed.

This is a diagnostic, not a reward. Optimising a policy to match a placement
histogram would produce something that stands in the right places for the wrong
reasons - the same error as training on a win rate, wearing a different hat.
Read it as evidence about behaviour, alongside a match result rather than
instead of one.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Detector class -> the simulator's card name, for the 2.6 deck plus the
# common cards that show up often enough in the footage to have a stable
# distribution.
CLASS_TO_CARD = {
    "hog-rider": "hog_rider", "musketeer": "musketeer", "cannon": "cannon",
    "ice-golem": "ice_golem", "skeleton": "skeletons", "the-log": "the_log",
    "ice-spirit": "ice_spirit", "fireball": "fireball", "knight": "knight",
    "valkyrie": "valkyrie", "giant": "giant", "wizard": "wizard",
}

# Below this many observations a card's distribution is not a reference.
MIN_PRO = 40
MIN_POLICY = 15


def pro_reference(path: Path) -> dict[str, dict]:
    """Median placement and spread per card, from the recorded footage."""
    by_card = collections.defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        card = CLASS_TO_CARD.get(p["card"])
        if card:
            by_card[card].append((p["tile_x"], p["tile_y"]))
    out = {}
    for card, points in by_card.items():
        if len(points) < MIN_PRO:
            continue
        out[card] = {
            "n": len(points),
            "x": statistics.median(p[0] for p in points),
            "y": statistics.median(p[1] for p in points),
            "spread_x": statistics.pstdev(p[0] for p in points),
            "spread_y": statistics.pstdev(p[1] for p in points),
        }
    return out


def policy_placements(checkpoint: Path, episodes: int, seed: int,
                      opponent: str) -> dict[str, list]:
    """Where a checkpoint actually puts things, over a run of matches."""
    import numpy as np
    import torch

    from sim.env import ClashEnv, CARD_ACTIONS, GRID_W, DECK_26
    from sim.train_ppo import build_network, masked_distribution
    from sim.env import NUM_PLANES, NUM_SCALARS, ACTIONS

    blob = torch.load(checkpoint, map_location="cpu", weights_only=False)
    net = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
    net.load_state_dict(blob["state_dict"])
    net.eval()

    found = collections.defaultdict(list)
    for episode in range(episodes):
        env = ClashEnv(seed=seed + episode, opponent=opponent)
        obs, info = env.reset()
        done = False
        while not done:
            with torch.no_grad():
                planes = torch.from_numpy(obs["planes"]).unsqueeze(0)
                scalars = torch.from_numpy(obs["scalars"]).unsqueeze(0)
                logits, _ = net(planes, scalars)
                # The env hands the legal mask back with the observation, the
                # same way evaluate_pilot reads it. Recomputing it here would
                # be a second implementation of the rule and a chance to
                # disagree with the one that actually gates the step.
                mask = torch.from_numpy(info["action_mask"]).unsqueeze(0)
                action = int(masked_distribution(logits, mask).probs.argmax())
            if 0 < action < CARD_ACTIONS:
                index = action - 1
                slot, cell = divmod(index, 576)
                y, x = divmod(cell, GRID_W)
                hand = env.match.players[1].hand
                if slot < len(hand):
                    found[hand[slot]].append((float(x), float(y)))
            obs, _, term, trunc, info = env.step(action)
            done = term or trunc
        env.close()
    return found


def compare(pro: dict, policy: dict) -> str:
    lines = [f"{'card':<14}{'n':>5}{'policy x,y':>14}{'pro x,y':>14}"
             f"{'offset':>9}{'spread':>9}",
             "-" * 66]
    offsets, ratios = [], []
    for card, ref in sorted(pro.items()):
        points = policy.get(card, [])
        if len(points) < MIN_POLICY:
            continue
        px = statistics.median(p[0] for p in points)
        py = statistics.median(p[1] for p in points)
        sx = statistics.pstdev(p[0] for p in points) if len(points) > 1 else 0.0
        offset = math.dist((px, py), (ref["x"], ref["y"]))
        ratio = sx / ref["spread_x"] if ref["spread_x"] else float("nan")
        offsets.append(offset)
        ratios.append(ratio)
        lines.append(f"{card:<14}{len(points):>5}"
                     f"{px:>7.1f},{py:<6.1f}{ref['x']:>7.1f},{ref['y']:<6.1f}"
                     f"{offset:>9.1f}{ratio:>9.2f}")
    if offsets:
        lines.append("")
        lines.append(f"median offset from pro placement : {statistics.median(offsets):.1f} tiles")
        lines.append(f"median spread ratio              : {statistics.median(ratios):.2f}"
                     "   (1.0 = varies like a person, <1 = same spot every time)")
    else:
        lines.append("(no card had enough placements from both sources)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ckpt", required=True, type=Path)
    ap.add_argument("--plays", type=Path, default=ROOT / "data" / "vod" / "plays.jsonl")
    ap.add_argument("--episodes", type=int, default=12)
    ap.add_argument("--seed", type=int, default=8000)
    ap.add_argument("--opponent", default="brain")
    args = ap.parse_args()

    pro = pro_reference(args.plays)
    if not pro:
        raise SystemExit(f"no usable reference in {args.plays}")
    print(f"reference: {len(pro)} cards from recorded play")
    policy = policy_placements(args.ckpt, args.episodes, args.seed, args.opponent)
    print(f"policy   : {sum(len(v) for v in policy.values())} placements over "
          f"{args.episodes} matches\n")
    print(compare(pro, policy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
