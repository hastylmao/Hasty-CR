"""Train a policy in the headless environment with PPO.

Two purposes, and the second is the one that matters soonest.

1. A learned policy, eventually better than the hand-written one.
2. **A sparring partner.** The simulator's problem is that it has no opponent
   resembling the ladder: the mirror defends exactly as well as we attack, and
   `SimpleOpponent` loses 99.7% of the time. Every sweep run here has therefore
   answered "does this beat a copy of me", which is not the question. An agent
   trained to beat the hand-written brain is the first opponent in this project
   that is neither trivial nor identical to us.

Design choices worth knowing:

**Masked logits, not penalties.** ~2,300 actions with a few dozen legal at any
moment cannot be learned by rejection. Illegal logits are set to -inf before the
softmax, so the policy only ever assigns probability to legal moves and the
entropy term measures something real.

**A small network on purpose.** The observation is 8x32x18 planes plus 47
scalars - closer to a board game than to pixels - and this shares a GPU with the
detector the live bot is using. Three conv layers is enough, and keeps a rollout
step cheaper than the environment step that produced it.

**Evaluation is greedy and against the brain.** Training reward is shaped by
tower damage, so it does not directly answer "does this win". Every eval runs
argmax actions against the hand-written policy and reports the record.

    python -m sim.train_ppo --envs 6 --steps 2000000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

OUT = ROOT / "tmp" / "rl"
LOG = ROOT / "tmp" / "live" / "rl_train.log"


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


@dataclass
class Hyper:
    envs: int = 6
    rollout: int = 128
    epochs: int = 4
    minibatches: int = 4
    gamma: float = 0.997          # ~360 steps an episode; credit must travel far
    gae_lambda: float = 0.95
    clip: float = 0.2
    value_coef: float = 0.5
    entropy_coef: float = 0.01
    max_grad_norm: float = 0.5
    lr: float = 3e-4


def entropy_schedule(step: int, start: float, final: Optional[float],
                     hold: int, anneal: int) -> float:
    """The entropy bonus at `step`: flat at `start`, then linear to `final`.

    Explore-then-exploit, in absolute step numbers rather than fractions of
    the run. A schedule written as "the first third" silently changes shape
    when the step budget does, and these boundaries were picked against a
    measured usage curve - fireball at 0.7% of plays and musketeer at 0.6%,
    the two cards that convert chip damage into a crown - not against the
    length of whatever run happens to be executing.

    `final` of None is a constant coefficient, which is what every run before
    this one used. `anneal <= hold` is a step change at `hold` rather than an
    error: it is a degenerate schedule, not an ambiguous one.
    """
    if final is None:
        return start
    if step <= hold:
        return start
    if anneal <= hold or step >= anneal:
        return final
    travelled = (step - hold) / (anneal - hold)
    return start + travelled * (final - start)


def build_network(num_planes: int, num_scalars: int, num_actions: int):
    import torch.nn as nn

    class Policy(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv2d(num_planes, 32, 3, padding=1), nn.ReLU(),
                nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(),
                nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(),
                nn.Flatten(),
            )
            self.scalar = nn.Sequential(nn.Linear(num_scalars, 128), nn.ReLU())
            self.trunk = nn.Sequential(
                nn.Linear(64 * 32 * 18 + 128, 512), nn.ReLU())
            self.policy = nn.Linear(512, num_actions)
            self.value = nn.Linear(512, 1)

        def forward(self, planes, scalars):
            features = self.trunk(torch_cat([self.conv(planes), self.scalar(scalars)]))
            return self.policy(features), self.value(features).squeeze(-1)

    return Policy()


def torch_cat(tensors):
    import torch
    return torch.cat(tensors, dim=1)


def masked_distribution(logits, mask):
    import torch
    from torch.distributions import Categorical

    # -inf on illegal actions. A row with no legal action cannot happen - index
    # 0 (hold) is always legal - but guard anyway rather than emit NaNs.
    logits = logits.masked_fill(~mask, float("-inf"))
    safe = mask.any(dim=1, keepdim=True)
    logits = torch.where(safe, logits, torch.zeros_like(logits))
    return Categorical(logits=logits)


def evaluate(network, device, episodes: int = 12, seed: int = 900_000,
             opponent: str = "brain", rewards=None) -> dict:
    """Greedy rollouts against whatever the run is training on.

    Evaluating on a different opponent than training would report a number that
    is not the one being optimised, so this takes the same setting.
    """
    import torch
    from sim.env import ClashEnv

    env = ClashEnv(seed=seed, opponent=opponent, rewards=rewards)
    wins = losses = draws = 0
    crowns_for = crowns_against = 0
    hog = plays = 0
    for episode in range(episodes):
        obs, info = env.reset(seed=seed + episode)
        while True:
            with torch.no_grad():
                planes = torch.from_numpy(obs["planes"]).unsqueeze(0).to(device)
                scalars = torch.from_numpy(obs["scalars"]).unsqueeze(0).to(device)
                mask = torch.from_numpy(info["action_mask"]).unsqueeze(0).to(device)
                logits, _ = network(planes, scalars)
                action = int(masked_distribution(logits, mask).probs.argmax())
            obs, _, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                break
        mine, theirs = info["crowns"]
        crowns_for += mine
        crowns_against += theirs
        wins += info["result"] == "bottom"
        losses += info["result"] == "top"
        draws += info["result"] not in ("bottom", "top")
        stats = info["stats"]
        plays += stats.plays
        hog += stats.cards.get("hog_rider", 0)
    env.close()
    return {"wins": wins, "losses": losses, "draws": draws,
            "crowns_for": crowns_for, "crowns_against": crowns_against,
            "hog_share": hog / plays if plays else 0.0,
            "plays_per_match": plays / max(1, episodes)}


def main() -> int:
    parser = argparse.ArgumentParser(description="PPO in the Clash simulator")
    parser.add_argument("--steps", type=int, default=2_000_000)
    parser.add_argument("--envs", type=int, default=6)
    parser.add_argument("--rollout", type=int, default=128)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--crown", type=float, default=3.0,
                        help="reward per crown. At the default of 3 against a "
                             "tower-damage weight of 10, a policy that chips "
                             "and wins the overtime tiebreak scores nearly as "
                             "well as one that takes a tower - which is how a "
                             "30M-step run ended up never playing its win "
                             "condition and taking zero crowns in 60 games")
    parser.add_argument("--win", type=float, default=10.0,
                        help="reward for winning the match outright")
    parser.add_argument("--chip", type=float, default=10.0,
                        help="reward per tower fraction dealt, and the penalty "
                             "per fraction taken")
    parser.add_argument("--elixir", type=float, default=0.0,
                        help="reward per net elixir traded. Scores the part of "
                             "the game tower damage cannot see - kiting, "
                             "pulling a tank into both towers, answering four "
                             "elixir with two. Off by default")
    parser.add_argument("--entropy", type=float, default=0.01,
                        help="entropy bonus. 0.01 collapsed to 0.02 nats by a "
                             "million steps on the 2321-action masked space - "
                             "deterministic, never playing its win condition, "
                             "and losing 13 of 16. Raise it before assuming "
                             "the policy or the reward is at fault")
    parser.add_argument("--entropy-final", type=float,
                        help="anneal the entropy bonus to this by "
                             "--entropy-anneal steps. Omit for a constant "
                             "coefficient. Explore-then-exploit: the measured "
                             "failure at 43%% vs the rule engine is not a "
                             "reward failure (return/win r = 0.967) but an "
                             "exploration one - fireball 0.7%% of plays and "
                             "musketeer 0.6%%, so the finishing actions that "
                             "convert chip into crowns are never tried often "
                             "enough to be reinforced. A high coefficient "
                             "early finds them; holding it there would keep "
                             "the policy noisy once it has")
    parser.add_argument("--entropy-hold", type=int, default=0,
                        help="steps to hold --entropy before annealing starts")
    parser.add_argument("--entropy-anneal", type=int, default=0,
                        help="step at which the coefficient reaches "
                             "--entropy-final")
    parser.add_argument("--eval-every", type=int, default=150_000)
    parser.add_argument("--eval-episodes", type=int, default=12)
    parser.add_argument("--name", default="ppo")
    parser.add_argument("--opponent", default="meta",
                        choices=("meta", "brain", "simple", "mirror"),
                        help="meta draws a different real ladder deck each "
                             "episode; brain is the hand-written policy on our "
                             "own deck, which is the mirror this project spent "
                             "a long time answering the wrong question against")
    parser.add_argument("--brain-share", type=float, default=0.0,
                        help="of the episodes that are not self-play, the "
                             "fraction played against the rule engine rather "
                             "than meta decks. Requires --opponent meta so the "
                             "deck pool is loaded. Training against one "
                             "opponent produces a policy that beats that "
                             "opponent: 50%% rule engine gave 93.3%% against "
                             "it and 76.7%% against meta decks, while the "
                             "all-meta arrangement gave 82.5%% and 16.7%% the "
                             "other way. Both were measured here")
    parser.add_argument("--scripted-alt", default="meta",
                        choices=("meta", "mirror", "simple"),
                        help="the non-rule-engine half of the "
                             "scripted episodes. `meta` for a "
                             "ladder policy; `mirror` for a 2.6 "
                             "mirror specialist, where variety "
                             "has to come from how the deck is "
                             "played rather than from the deck")
    parser.add_argument("--eval-opponent", default="",
                        help="who the periodic eval scores against; defaults "
                             "to --opponent. Worth separating precisely when "
                             "the training diet is mixed - the number that "
                             "selects a checkpoint should be the one you care "
                             "about, and it should not be an opponent the "
                             "policy has been trained to death against")
    parser.add_argument("--target-kl", type=float, default=0.02,
                        help="stop the epoch loop once the policy has moved "
                             "this far from the one that collected the batch. "
                             "PPO's clip bounds the ratio per action, not the "
                             "distance travelled over 4 epochs x 4 "
                             "minibatches, and a behaviour clone starts at "
                             "top-1 probability 0.99 - so sixteen unbounded "
                             "steps a rollout is enough to walk it off a "
                             "policy worth 75%%. Five runs did exactly that. "
                             "0 disables")
    parser.add_argument("--value-warmup", type=int, default=0,
                        help="steps spent fitting the critic before the policy "
                             "is allowed to move. `sim/clone.py` trains only "
                             "the action head - `criterion(logits, target)` - "
                             "so a behaviour clone arrives with a good policy "
                             "and a RANDOM value head. PPO advantages are "
                             "returns minus values, so the first updates are "
                             "noise scaled by a garbage critic, and they shred "
                             "the clone. Three runs regressed from a 75%% clone "
                             "to 35%% before this was found. Use ~300k with "
                             "--init")
    parser.add_argument("--value-warmup-lr", type=float, default=1e-3,
                        help="learning rate during value warmup. Much larger "
                             "than the PPO rate on purpose: the policy is "
                             "frozen so nothing it could damage is learning, "
                             "and at the fine-tuning rate of 5e-5 the critic "
                             "barely moves before the warmup budget is spent")
    parser.add_argument("--league", type=int, default=0,
                        help="keep this many past selves as opponents. The "
                             "reason to: a scripted opponent cannot punish "
                             "passivity, so training against one let a policy "
                             "take zero crowns in sixty matches, never play "
                             "Hog Rider, and still win a third of them on the "
                             "overtime tiebreak. An opponent that learns takes "
                             "the tower while you chip")
    parser.add_argument("--scripted-share", type=float, default=0.4,
                        help="fraction of episodes still played against the "
                             "meta deck pool. Never 0: a league that only "
                             "plays itself gets good at its own metagame and "
                             "loses to an ordinary ladder deck")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--init", type=Path,
                        help="start from these weights without their optimiser "
                             "state - for beginning PPO from a behaviour clone")
    args = parser.parse_args()

    import torch
    import torch.nn as nn
    from sim.env import ACTIONS, NUM_PLANES, NUM_SCALARS
    from sim.vecenv import VecClashEnv

    hyper = Hyper(envs=args.envs, rollout=args.rollout, lr=args.lr,
                  entropy_coef=args.entropy)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    OUT.mkdir(parents=True, exist_ok=True)

    network = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS).to(device)
    optimiser = torch.optim.Adam(network.parameters(), lr=hyper.lr, eps=1e-5)
    start_step = 0
    if args.init and args.init.exists():
        # Weights only. Starting from the behaviour clone means starting from a
        # policy that already sends a Hog, but its optimiser state belongs to a
        # supervised objective at a different learning rate, and carrying that
        # momentum into PPO is not resuming anything - it is noise.
        blob = torch.load(args.init, map_location=device, weights_only=False)
        network.load_state_dict(blob["state_dict"])
        log(f"initialised from {args.init} (weights only, step counter at 0)")
    if args.resume and args.resume.exists():
        blob = torch.load(args.resume, map_location=device, weights_only=False)
        network.load_state_dict(blob["state_dict"])
        optimiser.load_state_dict(blob["optimiser"])
        start_step = int(blob.get("step", 0))
        log(f"resumed {args.resume} at {start_step:,} steps")

    parameters = sum(p.numel() for p in network.parameters())
    log(f"PPO start: {args.envs} envs, {parameters/1e6:.1f}M params, device={device}, "
        f"target {args.steps:,} steps")

    from sim.env import RewardWeights
    reward_weights = RewardWeights(
        tower_damage_dealt=args.chip, tower_damage_taken=-args.chip,
        crown_for=args.crown, crown_against=-args.crown,
        win=args.win, loss=-args.win, elixir_traded=args.elixir)
    log(f"rewards: chip {args.chip}  crown {args.crown}  win {args.win}  elixir {args.elixir}  lr {args.lr}")
    vec = VecClashEnv(num_envs=hyper.envs, base_seed=1234,
                      opponent=args.opponent, rewards=reward_weights,
                      scripted_share=(args.scripted_share if args.league else 1.0),
                      brain_share=args.brain_share,
                      alt_kind=args.scripted_alt)
    eval_opponent = args.eval_opponent or args.opponent
    league_dir = OUT / f"{args.name}_league"
    if args.league:
        league_dir.mkdir(parents=True, exist_ok=True)
        for stale in league_dir.glob("*.pt"):
            stale.unlink()
        # Naming the actual opponent rather than always saying "meta decks",
        # which is what this printed regardless of --opponent. It is the line
        # you read to check the training diet, and it reported a run spending
        # half its episodes against the rule engine as if they were meta decks.
        if args.brain_share > 0.0:
            scripted = (f"{args.brain_share:.0%} rule engine / "
                        f"{1 - args.brain_share:.0%} {args.scripted_alt}")
        else:
            scripted = f"{args.opponent}"
        log(f"self-play league on: up to {args.league} past selves, "
            f"{args.scripted_share:.0%} of episodes vs {scripted}; "
            f"eval scores against {eval_opponent}")
    obs, masks = vec.reset()
    step = start_step
    best = -1e9
    next_eval = step + args.eval_every
    started = time.time()
    finished_episodes = 0
    recent_returns: list[float] = []
    running = np.zeros(hyper.envs, dtype=np.float32)

    def set_warmup(active: bool) -> None:
        """During warmup only the value head learns.

        Freezing the trunk as well as the policy head matters: backpropagating
        the value loss into shared features would move the policy too, which
        is the exact damage this is here to prevent. With everything but
        `network.value` frozen, the policy is bit-identical when warmup ends.
        """
        for name, parameter in network.named_parameters():
            parameter.requires_grad_(not active or name.startswith("value"))

    def entropy_coef_at(at_step: int) -> float:
        return entropy_schedule(at_step, hyper.entropy_coef, args.entropy_final,
                                args.entropy_hold, args.entropy_anneal)

    if args.entropy_final is not None:
        log(f"entropy schedule: {hyper.entropy_coef} held to "
            f"{args.entropy_hold:,}, then linear to {args.entropy_final} by "
            f"{args.entropy_anneal:,}")

    warmup_until = step + args.value_warmup
    in_warmup = step < warmup_until
    set_warmup(in_warmup)
    if in_warmup:
        for group in optimiser.param_groups:
            group["lr"] = args.value_warmup_lr
        log(f"value warmup: policy frozen for {args.value_warmup:,} steps "
            f"while the critic fits, lr {args.value_warmup_lr}")

    batch = hyper.envs * hyper.rollout
    try:
        while step < args.steps:
            buf_planes = np.zeros((hyper.rollout, hyper.envs, NUM_PLANES, 32, 18), np.float32)
            buf_scalars = np.zeros((hyper.rollout, hyper.envs, NUM_SCALARS), np.float32)
            buf_masks = np.zeros((hyper.rollout, hyper.envs, ACTIONS), bool)
            buf_actions = np.zeros((hyper.rollout, hyper.envs), np.int64)
            buf_logprobs = np.zeros((hyper.rollout, hyper.envs), np.float32)
            buf_values = np.zeros((hyper.rollout, hyper.envs), np.float32)
            buf_rewards = np.zeros((hyper.rollout, hyper.envs), np.float32)
            buf_dones = np.zeros((hyper.rollout, hyper.envs), np.float32)

            for t in range(hyper.rollout):
                buf_planes[t] = obs["planes"]
                buf_scalars[t] = obs["scalars"]
                buf_masks[t] = masks
                with torch.no_grad():
                    planes = torch.from_numpy(obs["planes"]).to(device)
                    scalars = torch.from_numpy(obs["scalars"]).to(device)
                    mask_t = torch.from_numpy(masks).to(device)
                    logits, value = network(planes, scalars)
                    dist = masked_distribution(logits, mask_t)
                    action = dist.sample()
                    buf_logprobs[t] = dist.log_prob(action).cpu().numpy()
                    buf_values[t] = value.cpu().numpy()
                    buf_actions[t] = action.cpu().numpy()

                obs, masks, rewards, dones, infos = vec.step(buf_actions[t])
                buf_rewards[t] = rewards
                buf_dones[t] = dones.astype(np.float32)
                running += rewards
                for index, done in enumerate(dones):
                    if done:
                        finished_episodes += 1
                        recent_returns.append(float(running[index]))
                        running[index] = 0.0
                step += hyper.envs

            with torch.no_grad():
                planes = torch.from_numpy(obs["planes"]).to(device)
                scalars = torch.from_numpy(obs["scalars"]).to(device)
                _, last_value = network(planes, scalars)
                last_value = last_value.cpu().numpy()

            advantages = np.zeros_like(buf_rewards)
            gae = np.zeros(hyper.envs, np.float32)
            for t in reversed(range(hyper.rollout)):
                nextnonterminal = 1.0 - buf_dones[t]
                nextvalue = last_value if t == hyper.rollout - 1 else buf_values[t + 1]
                delta = (buf_rewards[t] + hyper.gamma * nextvalue * nextnonterminal
                         - buf_values[t])
                gae = delta + hyper.gamma * hyper.gae_lambda * nextnonterminal * gae
                advantages[t] = gae
            returns = advantages + buf_values

            flat = lambda a, shape: torch.from_numpy(a.reshape(shape)).to(device)
            b_planes = flat(buf_planes, (batch, NUM_PLANES, 32, 18))
            b_scalars = flat(buf_scalars, (batch, NUM_SCALARS))
            b_masks = flat(buf_masks, (batch, ACTIONS))
            b_actions = flat(buf_actions, (batch,))
            b_logprobs = flat(buf_logprobs, (batch,))
            b_advantages = flat(advantages, (batch,))
            b_returns = flat(returns, (batch,))

            indices = np.arange(batch)
            size = batch // hyper.minibatches
            approx_kl = 0.0
            stopped_early = False
            # Fixed for the whole update, not recomputed per minibatch: the
            # sixteen gradient steps below all optimise the same objective.
            entropy_coef = entropy_coef_at(step)
            for _ in range(hyper.epochs):
                if stopped_early:
                    break
                np.random.shuffle(indices)
                for start in range(0, batch, size):
                    sel = torch.from_numpy(indices[start:start + size]).to(device)
                    logits, value = network(b_planes[sel], b_scalars[sel])
                    dist = masked_distribution(logits, b_masks[sel])
                    logprob = dist.log_prob(b_actions[sel])
                    logratio = logprob - b_logprobs[sel]
                    ratio = logratio.exp()
                    with torch.no_grad():
                        # Schulman's low-variance estimator. Always >= 0, which
                        # the naive -logratio mean is not, so it can be
                        # compared against a threshold without the sign
                        # flapping around zero.
                        approx_kl = float(((ratio - 1) - logratio).mean())
                    adv = b_advantages[sel]
                    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
                    loss_policy = torch.max(
                        -adv * ratio,
                        -adv * torch.clamp(ratio, 1 - hyper.clip, 1 + hyper.clip)).mean()
                    loss_value = ((value - b_returns[sel]) ** 2).mean()
                    entropy = dist.entropy().mean()
                    if in_warmup:
                        # No policy term and no entropy term: the policy is
                        # frozen, and an entropy bonus on frozen weights is
                        # just a constant.
                        loss = hyper.value_coef * loss_value
                    else:
                        loss = (loss_policy + hyper.value_coef * loss_value
                                - entropy_coef * entropy)
                    optimiser.zero_grad(set_to_none=True)
                    loss.backward()
                    nn.utils.clip_grad_norm_(network.parameters(), hyper.max_grad_norm)
                    optimiser.step()

                    if (args.target_kl and not in_warmup
                            and approx_kl > args.target_kl):
                        # Leave the rest of this batch on the table. The data
                        # was collected under a policy this one is no longer
                        # close to, so the remaining minibatches would be
                        # optimising a ratio that no longer means anything.
                        stopped_early = True
                        break

            if in_warmup and step >= warmup_until:
                in_warmup = False
                set_warmup(False)
                for group in optimiser.param_groups:
                    group["lr"] = hyper.lr
                log(f"value warmup done at {step:,} steps "
                    f"(value_loss {float(loss_value):.2f}); policy unfrozen "
                    f"at lr {hyper.lr}")
                next_eval = min(next_eval, step + 1)   # check the clone survived

            rate = (step - start_step) / max(1e-6, time.time() - started)
            mean_return = float(np.mean(recent_returns[-40:])) if recent_returns else 0.0
            log(f"step {step:>9,}{'  warmup' if in_warmup else '        '}  "
                f"{rate:6.0f}/s  episodes {finished_episodes:>5d}  "
                f"return {mean_return:7.2f}  entropy {float(entropy):5.2f}  "
                f"ecoef {entropy_coef:5.3f}  "
                f"value_loss {float(loss_value):8.2f}  "
                f"kl {approx_kl:6.4f}{' STOP' if stopped_early else ''}")

            if step >= next_eval:
                next_eval = step + args.eval_every
                network.eval()
                result = evaluate(network, device, args.eval_episodes,
                                  opponent=eval_opponent,
                                  rewards=reward_weights)
                network.train()
                # Both halves on purpose. Crown differential alone is what a
                # chip policy scores nothing on, so it is the term that stops
                # "never attack" being selected; the record is what we
                # actually care about on ladder. Selecting on the record alone
                # would happily keep a 0-crown tiebreak winner.
                played = max(1, args.eval_episodes)
                score = ((result["wins"] - result["losses"]) / played
                         + (result["crowns_for"] - result["crowns_against"]) / played)
                log(f"EVAL  W{result['wins']} L{result['losses']} D{result['draws']}  "
                    f"crowns {result['crowns_for']}-{result['crowns_against']}  "
                    f"hog {result['hog_share']:.0%}  "
                    f"plays/match {result['plays_per_match']:.0f}  score {score:+.2f}")
                blob = {"state_dict": network.state_dict(),
                        "optimiser": optimiser.state_dict(),
                        "step": step, "eval": result, "hyper": asdict(hyper)}
                torch.save(blob, OUT / f"{args.name}_last.pt")
                if args.league:
                    # Written whole, then moved into place: a worker that
                    # samples a half-written file would load garbage, and the
                    # seat swallows the error silently rather than crash.
                    snap = league_dir / f"step{step}.pt"
                    partial = snap.with_suffix(".part")
                    torch.save({"state_dict": network.state_dict()}, partial)
                    partial.replace(snap)
                    size = vec.league_add(snap, f"self@{step//1000}k")
                    if size > args.league:
                        vec.league_trim(args.league)
                        keep = sorted(league_dir.glob("*.pt"))
                        for old_snap in keep[1:-(args.league - 1)] if args.league > 1 else keep[1:]:
                            old_snap.unlink(missing_ok=True)
                    log(f"      league: {min(size, args.league)} past selves on the top seat")
                if score > best:
                    best = score
                    torch.save(blob, OUT / f"{args.name}_best.pt")
                    (OUT / f"{args.name}_best.json").write_text(
                        json.dumps({"step": step, **result}, indent=1), encoding="utf-8")
                    log(f"      new best ({score:+.2f}) -> {args.name}_best.pt")
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        vec.close()
        torch.save({"state_dict": network.state_dict(),
                    "optimiser": optimiser.state_dict(), "step": step},
                   OUT / f"{args.name}_last.pt")
        log(f"stopped at {step:,} steps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
