"""Play one checkpoint against another, both sides greedy, same deck.

The scripted opponents stop being instruments once a policy saturates them.
Measured on this project: a mirror-trained policy reads 93.3% against the rule
engine and 100.0% against the scripted 2.6 styles, and three million further
steps moved neither number outside its confidence interval. That is not
evidence the training did nothing - it is evidence that a 60-0 opponent cannot
tell "good" from "better".

Two policies playing each other can. In a mirror the deck is identical, the
seats are symmetric, and the only asymmetry is the policy, so the win rate is
a direct comparison with no third party's competence in the way.

**Seats are swapped every other game.** The bottom seat is not neutral - it
deploys first in the observation ordering and the arena is only symmetric up
to the mirror this project spent a long time getting exact - so a fixed seat
would measure the seat as much as the policy. An odd `--games` is rejected for
the same reason.

    python -m scripts.head_to_head --a checkpoints/night/best.pt \
                                   --b checkpoints/ladder/ladder_best.pt --games 60
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def load(path: Path, device: str):
    import torch
    from sim.env import ACTIONS, NUM_PLANES, NUM_SCALARS
    from sim.train_ppo import build_network
    blob = torch.load(str(path), map_location=device, weights_only=False)
    net = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS).to(device)
    net.load_state_dict(blob["state_dict"])
    net.eval()
    return net, int(blob.get("step", 0))


def play(net_a, net_b, games: int, seed: int, device: str) -> dict:
    import torch
    from sim.env import ClashEnv
    from sim.selfplay import PolicyOpponent
    from sim.train_ppo import masked_distribution

    env = ClashEnv(seed=seed, opponent="mirror")
    wins = losses = draws = 0
    crowns_for = crowns_against = 0
    for game in range(games):
        # Swap which network holds the bottom seat every other game.
        agent, other = (net_a, net_b) if game % 2 == 0 else (net_b, net_a)
        env.set_policy_opponent(PolicyOpponent(other, env._cards, side=-1,
                                               seed=seed + game,
                                               temperature=0.0))
        obs, info = env.reset(seed=seed + game)
        while True:
            with torch.no_grad():
                planes = torch.from_numpy(obs["planes"]).unsqueeze(0).to(device)
                scalars = torch.from_numpy(obs["scalars"]).unsqueeze(0).to(device)
                mask = torch.from_numpy(info["action_mask"]).unsqueeze(0).to(device)
                logits, _ = agent(planes, scalars)
                action = int(masked_distribution(logits, mask).probs.argmax())
            obs, _reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                break
        mine, theirs = info["crowns"]
        won = info["result"] == "bottom"
        lost = info["result"] == "top"
        # Report everything from A's point of view regardless of which seat it
        # held this game, or swapping the seats would cancel out the result.
        if game % 2 == 1:
            won, lost = lost, won
            mine, theirs = theirs, mine
        wins += won
        losses += lost
        draws += not (won or lost)
        crowns_for += mine
        crowns_against += theirs
    env.close()
    low, high = wilson(wins, games)
    return {"games": games, "wins": wins, "losses": losses, "draws": draws,
            "win_rate": wins / games if games else 0.0,
            "wilson_lo": low, "wilson_hi": high,
            "crowns_for": crowns_for, "crowns_against": crowns_against,
            "crown_diff": (crowns_for - crowns_against) / max(1, games)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Two checkpoints, same deck")
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--games", type=int, default=60)
    parser.add_argument("--seed", type=int, default=8000)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.games % 2:
        print("--games must be even so each policy holds each seat equally",
              file=sys.stderr)
        return 2
    for path in (args.a, args.b):
        if not path.exists():
            print(f"missing checkpoint: {path}", file=sys.stderr)
            return 1

    device = "cpu"
    net_a, step_a = load(args.a, device)
    net_b, step_b = load(args.b, device)
    print(f"A: {args.a.name} (step {step_a:,})")
    print(f"B: {args.b.name} (step {step_b:,})")
    print(f"{args.games} games, seats swapped every game, both greedy\n")

    result = play(net_a, net_b, args.games, args.seed, device)
    print(f"  A wins {result['wins']}  losses {result['losses']}  "
          f"draws {result['draws']}")
    print(f"  win rate {result['win_rate']:.1%} "
          f"[{result['wilson_lo']:.1%}-{result['wilson_hi']:.1%}]")
    print(f"  crowns {result['crowns_for']}-{result['crowns_against']} "
          f"(diff {result['crown_diff']:+.2f})")
    # A coin flip is what two equally strong policies produce, so the useful
    # question is whether 50% is outside the interval, not whether A won.
    if result["wilson_lo"] > 0.5:
        print("\n  A is stronger; 50% is below the interval.")
    elif result["wilson_hi"] < 0.5:
        print("\n  B is stronger; 50% is above the interval.")
    else:
        print("\n  No separation: the interval contains 50%, so these two "
              "are not distinguishable at this sample size.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            {"a": str(args.a), "b": str(args.b), "step_a": step_a,
             "step_b": step_b, "seed": args.seed, **result}, indent=2),
            encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
