"""Shadow-mode advisor: observable state -> policy recommendation.

Does NOT control a real account. Reads a trained checkpoint and,
given an observation + action mask, returns ranked action recommendations.

Two modes:
  1. Offline trace: feed it a recorded game JSON or a sim env snapshot.
  2. Live stub: wraps the deployable observation adapter shape so the
     minimum missing bridge is explicit.

Usage:
    python -m scripts.shadow_advisor --ckpt tmp/rl/pilot_best.pt --top 5
    python -m scripts.shadow_advisor --ckpt tmp/rl/pilot_best.pt --interactive

The interactive demo runs a sim match and logs recommendations per decision.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)


def load_policy(ckpt: Path, device: str = "cpu"):
    import torch
    from sim.env import ACTIONS, NUM_PLANES, NUM_SCALARS
    from sim.train_ppo import build_network

    blob = torch.load(str(ckpt), map_location=device, weights_only=False)
    net = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS).to(device)
    net.load_state_dict(blob["state_dict"])
    net.eval()
    meta = {k: v for k, v in blob.items() if k != "state_dict"}
    return net, meta


def recommend(net, obs: dict, mask: np.ndarray, device: str = "cpu", top_k: int = 5) -> list[dict]:
    import torch
    from sim.train_ppo import masked_distribution
    from sim.env import ClashEnv

    with torch.no_grad():
        planes = torch.from_numpy(obs["planes"]).unsqueeze(0).to(device)
        scalars = torch.from_numpy(obs["scalars"]).unsqueeze(0).to(device)
        mask_t = torch.from_numpy(mask).unsqueeze(0).to(device)
        logits, value = net(planes, scalars)
        dist = masked_distribution(logits, mask_t)
        probs = dist.probs[0].cpu().numpy()
        logits_np = logits[0].cpu().numpy()

    # Rank legal actions by probability
    legal_idx = np.where(mask)[0]
    order = legal_idx[np.argsort(probs[legal_idx])[::-1]]
    out = []
    for rank, idx in enumerate(order[:top_k]):
        decoded = ClashEnv.decode(int(idx))
        if decoded is None:
            label = "HOLD"
        elif decoded[0] == "ability":
            label = f"ABILITY rank={decoded[1]}"
        else:
            slot, x, y = decoded
            label = f"PLAY slot={slot} tile=({x},{y})"
        out.append({
            "rank": rank + 1,
            "action": int(idx),
            "label": label,
            "prob": float(probs[idx]),
            "logit": float(logits_np[idx]),
        })
    return out, float(value[0].cpu().numpy()) if 'value' in locals() else 0.0


def interactive_demo(ckpt: Path, episodes: int = 2, top_k: int = 5) -> None:
    import torch
    from sim.env import ClashEnv

    device = "cuda" if torch.cuda.is_available() else "cpu"
    net, meta = load_policy(ckpt, device)
    print(f"loaded {ckpt}  step={meta.get('step')}  eval={meta.get('eval')}")

    for ep in range(episodes):
        env = ClashEnv(seed=9000 + ep, opponent="brain")
        obs, info = env.reset(seed=9000 + ep)
        print(f"\n=== episode {ep+1} ===")
        step = 0
        while True:
            recs, value = recommend(net, obs, info["action_mask"], device, top_k)
            ts = time.strftime("%H:%M:%S")
            # Log in shadow format
            best = recs[0] if recs else {"label": "HOLD", "prob": 1.0}
            print(f"[{ts}] step={step:3d}  elixir={obs['scalars'][0]*10:.1f}  "
                  f"value={value:+.2f}  -> {best['label']}  p={best['prob']:.2%}")
            top_str = ", ".join(f"{r['label']} {r['prob']:.0%}" for r in recs[:3])
            print(f"         top {top_k}: {top_str}")
            # Execute greedy for demo continuity
            action = recs[0]["action"] if recs else 0
            obs, _, term, trunc, info = env.step(action)
            step += 1
            if term or trunc:
                print(f"  result={info['result']}  crowns={info['crowns']}  plays={info['stats'].plays}")
                break
        env.close()

    print("\n--- Shadow bridge status ---")
    print("Current perception (src/hastycr/observation.py) provides:")
    print("  - GameState with allies/enemies boxes, elixir, hand, tower_hp")
    print("Missing bridge to full policy input (sim.env.observe):")
    print("  - Plane encoder expects sim Battle entities with exact positions/HP")
    print("  - Live detector boxes must be mapped to 32x18 grid planes")
    print("  - Tower fractions from HP OCR need calibration")
    print("  - Hand OCR -> DECK_26 one-hot must match training deck exactly")
    print("Recommendation: implement GameState -> env.observe adapter via")
    print("  arena homography + entity box->tile projection + HP normalization.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow advisor")
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--episodes", type=int, default=2)
    args = parser.parse_args()

    if args.interactive:
        interactive_demo(args.ckpt, args.episodes, args.top)
    else:
        interactive_demo(args.ckpt, 1, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
