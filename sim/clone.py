"""Teach the network to imitate the hand-written brain, before asking it to improve.

PPO from a random start does not work on this problem, and the failure is
instructive rather than mysterious. Over 1.25M steps the agent reached
`crowns_for = 0` in *every* evaluation while winning a third of its matches: it
had found the local optimum of spending cheap cards on defence and winning
time-out tiebreaks on tower health. Scoring a crown needs a coordinated sequence
- get elixir, put a tank at the bridge, put the Hog behind it, defend the
counter-push - and the chance of stumbling onto that by sampling from ~2,300
masked actions is negligible. So the reward is dense enough to learn defence and
far too sparse to learn offence.

Behaviour cloning removes the exploration problem instead of tuning around it.
The hand-written policy already knows how to attack; supervised learning on its
decisions gets the network to the same place in minutes, and PPO can then start
from a policy that at least sends a Hog.

Two details that matter for correctness:

**The teacher plays through the environment, not beside it.** Its chosen action
is the action the environment executes, so the recorded states are the states
that actually follow - on-policy for the teacher. Recording a teacher's opinion
of states produced by someone else's actions is a different and much weaker
dataset.

**"Hold" is most of the data.** The brain decides on roughly one step in ten, and
a classifier trained on that imbalance learns to output nothing. Hold examples
are therefore subsampled to a target share.

    python -m sim.clone --episodes 400
    python -m sim.train_ppo --resume tmp/rl/clone.pt --name ppo_from_clone
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

OUT = ROOT / "tmp" / "rl"
LOG = ROOT / "tmp" / "live" / "rl_train.log"


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} clone: {message}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def collect(episodes: int, hold_share: float = 0.25,
            seed: int = 500_000) -> Tuple[dict, np.ndarray]:
    """Play `episodes` matches with the brain in the agent's seat, recording it."""
    from sim.adapter import build_state
    from sim.env import ClashEnv
    from sim.runner import BrainPolicy

    env = ClashEnv(seed=seed)
    teacher = BrainPolicy(env._cards, side=1)

    planes: List[np.ndarray] = []
    scalars: List[np.ndarray] = []
    masks: List[np.ndarray] = []
    actions: List[int] = []
    holds = decisions = rejected = 0
    rng = random.Random(0)

    for episode in range(episodes):
        obs, info = env.reset(seed=seed + episode)
        teacher.reset()
        while True:
            state = build_state(env.match, 1, env._cards)
            now = env.match.elapsed_ms / 1000.0
            decision = teacher.brain.decide(state, now, now)

            action = 0
            if decision is not None:
                hand = env.match.players[1].hand
                if decision.card in hand:
                    slot = hand.index(decision.card)
                    candidate = ClashEnv.encode(slot, int(decision.x), int(decision.y))
                    if 0 <= candidate < len(info["action_mask"]) \
                            and info["action_mask"][candidate]:
                        action = candidate
                    else:
                        # The brain sometimes wants a tile the engine will not
                        # accept. Recording it would teach an illegal habit.
                        rejected += 1

            keep = action != 0 or rng.random() < hold_share
            if keep:
                planes.append(obs["planes"])
                scalars.append(obs["scalars"])
                masks.append(info["action_mask"])
                actions.append(action)
                holds += action == 0
                decisions += action != 0

            obs, _, terminated, truncated, info = env.step(action)
            if action != 0 and decision is not None:
                teacher.brain.confirm(decision, now)
            if terminated or truncated:
                break
        if (episode + 1) % 50 == 0:
            log(f"collected {episode + 1}/{episodes} episodes, "
                f"{decisions} plays, {holds} holds, {rejected} illegal wishes")

    env.close()
    data = {
        "planes": np.stack(planes),
        "scalars": np.stack(scalars),
        "masks": np.stack(masks),
    }
    return data, np.array(actions, dtype=np.int64)


def main() -> int:
    parser = argparse.ArgumentParser(description="Behaviour-clone the brain")
    parser.add_argument("--episodes", type=int, default=400)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--hold-share", type=float, default=0.25)
    parser.add_argument("--name", default="clone")
    args = parser.parse_args()

    import torch
    import torch.nn as nn
    from sim.env import ACTIONS, NUM_PLANES, NUM_SCALARS
    from sim.train_ppo import build_network, masked_distribution

    started = time.time()
    data, actions = collect(args.episodes, args.hold_share)
    played = int((actions != 0).sum())
    log(f"dataset {len(actions)} samples ({played} plays, "
        f"{len(actions) - played} holds) in {time.time() - started:.0f}s")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    network = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS).to(device)
    optimiser = torch.optim.AdamW(network.parameters(), lr=args.lr, weight_decay=1e-4)

    count = len(actions)
    split = int(count * 0.9)
    order = np.random.default_rng(0).permutation(count)
    train_idx, val_idx = order[:split], order[split:]

    def batch_of(index: np.ndarray):
        return (torch.from_numpy(data["planes"][index]).to(device),
                torch.from_numpy(data["scalars"][index]).to(device),
                torch.from_numpy(data["masks"][index]).to(device),
                torch.from_numpy(actions[index]).to(device))

    criterion = nn.CrossEntropyLoss()
    best = 0.0
    for epoch in range(args.epochs):
        network.train()
        np.random.shuffle(train_idx)
        total = 0.0
        for start in range(0, len(train_idx), args.batch):
            planes, scalars, masks, target = batch_of(train_idx[start:start + args.batch])
            logits, value = network(planes, scalars)
            logits = logits.masked_fill(~masks, float("-inf"))
            loss = criterion(logits, target)
            optimiser.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(network.parameters(), 1.0)
            optimiser.step()
            total += float(loss) * len(target)

        network.eval()
        correct = play_correct = play_total = 0
        with torch.no_grad():
            for start in range(0, len(val_idx), 1024):
                planes, scalars, masks, target = batch_of(val_idx[start:start + 1024])
                logits, _ = network(planes, scalars)
                predicted = masked_distribution(logits, masks).probs.argmax(1)
                correct += int((predicted == target).sum())
                is_play = target != 0
                play_total += int(is_play.sum())
                play_correct += int((predicted[is_play] == target[is_play]).sum())
        accuracy = correct / max(1, len(val_idx))
        play_accuracy = play_correct / max(1, play_total)
        log(f"epoch {epoch + 1}/{args.epochs}  loss {total / len(train_idx):.4f}  "
            f"val {accuracy:.3f}  on plays {play_accuracy:.3f}")
        if accuracy > best:
            best = accuracy
            OUT.mkdir(parents=True, exist_ok=True)
            torch.save({"state_dict": network.state_dict(),
                        "optimiser": optimiser.state_dict(),
                        "step": 0, "val_accuracy": accuracy},
                       OUT / f"{args.name}.pt")

    log(f"best val accuracy {best:.3f} -> {OUT / (args.name + '.pt')}")

    from sim.train_ppo import evaluate
    blob = torch.load(OUT / f"{args.name}.pt", map_location=device, weights_only=False)
    network.load_state_dict(blob["state_dict"])
    network.eval()
    result = evaluate(network, device, episodes=16)
    log(f"EVAL(clone)  W{result['wins']} L{result['losses']} D{result['draws']}  "
        f"crowns {result['crowns_for']}-{result['crowns_against']}  "
        f"hog {result['hog_share']:.0%}  plays/match {result['plays_per_match']:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
