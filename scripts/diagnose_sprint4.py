"""Lean 300-game Brain diagnostic logger for RL Sprint 4.

Plays the frozen baseline policy vs the hand-written brain and writes one JSON
per game under reports/rl_sprint4/matches/ with a lightweight per-decision-tick
trace plus final stats. This is deliberately a LEAN logger, not a debug
framework: no per-decision greedy re-evaluation, a single masked_distribution
call per step, cpu tensors, and compact serialization.

Reuse: sim/env.py:ClashEnv, sim/train_ppo.py:build_network + masked_distribution,
scripts/evaluate_pilot.py:evaluate_one seeding pattern (seed + ep*1000).

    python -m scripts.diagnose_sprint4 --episodes 300 --seed 8000
    python -m scripts.diagnose_sprint4 --episodes 10 --seed 8000   # smoke test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from sim.env import CARD_ACTIONS, DECK_26  # noqa: E402

# Scalar layout (sim/env.py): 0 elixir, 1 elapsed, 2 regen-mult,
# 3-4 our towers (left,right), 5-6 their towers, 7:39 hand one-hot (4x8),
# 39:47 next-card one-hot (8).
SC_ELIXIR = 0
SC_TOWERS = slice(3, 7)
SC_HAND = slice(7, 39)
SC_NEXT = slice(39, 47)


def _decode_hand(scalars) -> list[str]:
    hand = []
    onehot = scalars[SC_HAND].reshape(4, len(DECK_26))
    for slot in range(4):
        idx = int(onehot[slot].argmax())
        hand.append(DECK_26[idx] if onehot[slot][idx] > 0 else "?")
    return hand


def _decode_next(scalars) -> str:
    seg = scalars[SC_NEXT]
    idx = int(seg.argmax())
    return DECK_26[idx] if seg[idx] > 0 else "?"


def run(ckpt: Path, episodes: int, seed: int, out_dir: Path,
        device: str = "cpu") -> dict:
    import torch
    from sim.env import ACTIONS, NUM_PLANES, NUM_SCALARS, ClashEnv
    from sim.train_ppo import build_network, masked_distribution

    out_dir.mkdir(parents=True, exist_ok=True)
    blob = torch.load(str(ckpt), map_location=device, weights_only=False)
    net = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS).to(device)
    net.load_state_dict(blob["state_dict"])
    net.eval()

    env = ClashEnv(seed=seed, opponent="brain")
    summary = []
    t_start = time.time()

    for ep in range(episodes):
        ep_seed = seed + ep * 1000
        obs, info = env.reset(seed=ep_seed)
        ticks = []
        total_return = 0.0
        ep_t0 = time.time()

        while True:
            match = env.match
            scalars = obs["scalars"]
            mask = info["action_mask"]
            with torch.no_grad():
                planes = torch.from_numpy(obs["planes"]).unsqueeze(0).to(device)
                sc = torch.from_numpy(scalars).unsqueeze(0).to(device)
                mk = torch.from_numpy(mask).unsqueeze(0).to(device)
                logits, _ = net(planes, sc)
                probs = masked_distribution(logits, mk).probs[0]
                action = int(probs.argmax())

            hand = _decode_hand(scalars)
            placed = None
            if 0 < action < CARD_ACTIONS:
                slot, x, y = env.decode(action)
                if slot < len(hand) and hand[slot] != "?":
                    placed = {"card": hand[slot], "x": int(x), "y": int(y)}

            ticks.append({
                "t_ms": int(match.elapsed_ms),
                "elixir": float(scalars[SC_ELIXIR]) * 10.0,
                "hand": hand,
                "next": _decode_next(scalars),
                "action": action,
                "hold": action == 0,
                "legal": int(mask.sum()),
                "towers": [float(v) for v in scalars[SC_TOWERS]],
                "units_ours": float(obs["planes"][0].sum()),
                "units_theirs": float(obs["planes"][1].sum()),
                "placed": placed,
            })

            obs, reward, term, trunc, info = env.step(action)
            total_return += float(reward)
            if term or trunc:
                break

        match = env.match
        ours = sum(match.tower_fractions(1).values())
        theirs = sum(match.tower_fractions(-1).values())
        mine, their = info["crowns"]
        stats = info["stats"]
        game = {
            "seed": ep_seed,
            "result": info["result"],
            "crowns": [mine, their],
            "tower_for": float(ours),
            "tower_against": float(theirs),
            "duration_s": match.elapsed_ms / 1000.0,
            "plays": stats.plays,
            "illegal": stats.illegal,
            "cards": dict(stats.cards),
            "total_return": total_return,
            "n_ticks": len(ticks),
            "ticks": ticks,
        }
        path = out_dir / f"game_{ep_seed}.json"
        path.write_text(json.dumps(game), encoding="utf-8")

        winside = 1 if info["result"] == "bottom" else 0
        summary.append({
            "seed": ep_seed, "result": info["result"], "win": winside,
            "crowns": [mine, their], "tower_diff": float(ours - theirs),
            "return": total_return, "plays": stats.plays,
            "duration_s": match.elapsed_ms / 1000.0,
        })
        elapsed = time.time() - t_start
        rate = (ep + 1) / elapsed if elapsed > 0 else 0.0
        eta = (episodes - ep - 1) / rate if rate > 0 else 0.0
        print(f"[{ep+1:3d}/{episodes}] seed={ep_seed} "
              f"{'W' if winside else 'L'} crowns={mine}-{their} "
              f"tower_diff={ours-theirs:+.2f} ticks={len(ticks)} "
              f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")

    env.close()
    n = len(summary)
    wins = sum(s["win"] for s in summary)
    cf = sum(s["crowns"][0] for s in summary)
    ca = sum(s["crowns"][1] for s in summary)
    td = sum(s["tower_diff"] for s in summary) / max(1, n)
    wall = time.time() - t_start
    agg = {
        "episodes": n, "seed": seed, "wins": wins,
        "win_rate": wins / max(1, n),
        "crown_diff": (cf - ca) / max(1, n),
        "tower_diff": td, "wall_s": wall,
        "games_per_min": n / (wall / 60.0) if wall > 0 else 0.0,
    }
    (out_dir / "summary.json").write_text(
        json.dumps({"aggregate": agg, "games": summary}, indent=2),
        encoding="utf-8")
    print(f"\ndone: {n} games in {wall:.0f}s "
          f"({agg['games_per_min']:.1f} games/min) win={agg['win_rate']:.1%} "
          f"crown_diff={agg['crown_diff']:+.2f} tower_diff={td:+.2f}")
    return agg


def main() -> int:
    parser = argparse.ArgumentParser(description="Sprint 4 lean diagnostic logger")
    parser.add_argument("--ckpt", type=Path,
                        default=Path("checkpoints/sprint4_baseline/pilot_best_4392960.pt"))
    parser.add_argument("--episodes", type=int, default=300)
    parser.add_argument("--seed", type=int, default=8000)
    parser.add_argument("--out", type=Path,
                        default=Path("reports/rl_sprint4/matches"))
    args = parser.parse_args()
    run(args.ckpt, args.episodes, args.seed, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
