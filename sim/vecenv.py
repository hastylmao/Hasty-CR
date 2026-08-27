"""Run many ClashEnv instances in parallel, because one is nowhere near enough.

A single environment steps at roughly 800 decisions a second, and a match is
~360 decisions, so one worker produces about two matches a second. PPO on a
problem this size wants millions of steps, which is days on one core and hours
across eight.

Workers are processes, not threads: every step runs the hand-written brain for
the opponent, which is pure Python and holds the GIL throughout.

    vec = VecClashEnv(num_envs=8)
    obs, masks = vec.reset()
    obs, masks, rewards, dones, infos = vec.step(actions)

Observations come back stacked, so `planes` is (N, C, H, W) and `scalars` is
(N, S) - the shapes a torch policy wants without further work. Environments
auto-reset on termination, and the observation returned on a `done` step is the
first observation of the *next* episode, with the final one preserved in
`infos[i]["final"]`. That is the SB3/Gymnasium convention; getting it wrong
silently bootstraps value estimates across an episode boundary.
"""

from __future__ import annotations

import multiprocessing as mp
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)


class _LeagueSeat:
    """Picks who plays the top seat for the next episode, inside a worker.

    Snapshots are passed as *paths*, not weights. The network is 20M
    parameters - eighty megabytes - and broadcasting a pool of eight to twelve
    workers would be several gigabytes of duplicated tensors. Each worker loads
    what it samples and keeps a couple cached.
    """

    CACHE = 2

    def __init__(self, seed: int, scripted_share: float = 0.4,
                 brain_share: float = 0.0, alt_kind: str = "meta"):
        import random
        self.rng = random.Random(seed)
        self.scripted_share = scripted_share
        # Of the episodes that are not self-play, this fraction faces the rule
        # engine and the rest face `alt_kind`. 0 keeps the old behaviour: the
        # environment's own opponent, whatever it was built with.
        #
        # `alt_kind` is what makes this usable for a mirror run as well as a
        # ladder one. For ladder the other half should be meta decks, so the
        # policy sees other archetypes. For a 2.6 mirror there are no other
        # archetypes by definition, and the variety has to come from *how*
        # the mirror is played instead - so it is `mirror`, our own deck under
        # the scripted styles.
        self.brain_share = brain_share
        self.alt_kind = alt_kind
        self.entries: list[tuple[str, str]] = []
        self._cache: dict[str, object] = {}
        self._order: list[str] = []

    def add(self, path: str, label: str) -> None:
        self.entries.append((path, label))

    def trim(self, keep: int) -> None:
        if len(self.entries) > keep:
            # Keep the oldest as an anchor plus the most recent ones. Dropping
            # the anchor lets the whole league drift together, which is how a
            # self-play pool ends up strong only against its own metagame.
            self.entries = [self.entries[0]] + self.entries[-(keep - 1):]
        stale = set(self._cache) - {p for p, _ in self.entries}
        for path in stale:
            self._cache.pop(path, None)
            if path in self._order:
                self._order.remove(path)

    def _network(self, path: str):
        import torch
        from sim.env import ACTIONS, NUM_PLANES, NUM_SCALARS
        from sim.train_ppo import build_network
        if path in self._cache:
            return self._cache[path]
        blob = torch.load(path, map_location="cpu", weights_only=False)
        net = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
        net.load_state_dict(blob["state_dict"])
        net.eval()
        self._cache[path] = net
        self._order.append(path)
        while len(self._order) > self.CACHE:
            self._cache.pop(self._order.pop(0), None)
        return net

    def scripted_kind(self) -> str:
        """Which scripted opponent this episode should face."""
        return ("brain" if self.rng.random() < self.brain_share
                else self.alt_kind)

    def choose(self, env) -> None:
        """Set (or clear) the learned opponent on `env` for the next episode."""
        if not self.entries or self.rng.random() < self.scripted_share:
            env.set_policy_opponent(None)
            # Alternate the scripted opponent so the policy cannot specialise
            # into whichever one it always sees. Both failure directions have
            # now been measured on this project; see `set_opponent_kind`.
            if self.brain_share > 0.0:
                env.set_opponent_kind(self.scripted_kind())
            return
        path, label = self.entries[self.rng.randrange(len(self.entries))]
        try:
            net = self._network(path)
        except (OSError, RuntimeError, EOFError):
            env.set_policy_opponent(None)     # snapshot still being written
            return
        from sim.selfplay import PolicyOpponent
        # Temperature above one on purpose: a greedy frozen opponent is a
        # single script, and beating one script is what the last run did.
        opponent = PolicyOpponent(net, env._cards, side=-1,
                                  seed=self.rng.randrange(1 << 30),
                                  temperature=self.rng.choice((0.7, 1.0, 1.3)))
        opponent.name = label
        env.set_policy_opponent(opponent)


def _worker(remote, seed: int, kwargs: dict) -> None:
    from sim.env import ClashEnv

    # One thread per worker. With a learned opponent each worker runs a 20M
    # parameter forward pass every step, and torch defaults to a thread per
    # core *per process* - twelve workers then fight for the same cores and
    # every one of them gets slower. Pinning to one thread each is roughly a
    # threefold speedup at this worker count.
    try:
        import torch
        torch.set_num_threads(1)
    except ImportError:
        pass

    scripted_share = kwargs.pop("scripted_share", 0.4)
    brain_share = kwargs.pop("brain_share", 0.0)
    alt_kind = kwargs.pop("alt_kind", "meta")
    env = ClashEnv(seed=seed, **kwargs)
    seat = _LeagueSeat(seed=seed + 7, scripted_share=scripted_share,
                       brain_share=brain_share, alt_kind=alt_kind)
    try:
        while True:
            command, payload = remote.recv()
            if command == "league_add":
                seat.add(*payload)
                remote.send(("ok", len(seat.entries)))
            elif command == "league_trim":
                seat.trim(int(payload))
                remote.send(("ok", len(seat.entries)))
            elif command == "reset":
                seat.choose(env)
                obs, info = env.reset(payload)
                remote.send((obs, info["action_mask"]))
            elif command == "step":
                obs, reward, terminated, truncated, info = env.step(payload)
                done = terminated or truncated
                extra = {}
                if done:
                    stats = info["stats"]
                    extra = {
                        "final": {
                            "result": info["result"],
                            "crowns": info["crowns"],
                            "plays": stats.plays,
                            "illegal": stats.illegal,
                            "hog_share": stats.hog_share,
                            "steps": stats.steps,
                        }
                    }
                    extra["final"]["opponent"] = env.opponent_deck_name
                    seat.choose(env)
                    obs, info = env.reset()
                remote.send((obs, info["action_mask"], reward, done, extra))
            elif command == "close":
                remote.close()
                return
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        env.close()


class VecClashEnv:
    def __init__(self, num_envs: int = 8, base_seed: int = 0, **kwargs):
        self.num_envs = num_envs
        context = mp.get_context("spawn")
        self._remotes, self._workers = [], []
        for index in range(num_envs):
            parent, child = context.Pipe()
            process = context.Process(
                target=_worker,
                args=(child, base_seed + index * 100_000, kwargs),
                daemon=True)
            process.start()
            child.close()
            self._remotes.append(parent)
            self._workers.append(process)
        self.closed = False

    # ------------------------------------------------------------------ api

    def league_add(self, path, label: str) -> int:
        """Tell every worker about a new frozen opponent, by path."""
        for remote in self._remotes:
            remote.send(("league_add", (str(path), label)))
        sizes = [remote.recv()[1] for remote in self._remotes]
        return sizes[0] if sizes else 0

    def league_trim(self, keep: int) -> int:
        for remote in self._remotes:
            remote.send(("league_trim", int(keep)))
        sizes = [remote.recv()[1] for remote in self._remotes]
        return sizes[0] if sizes else 0

    def reset(self, seed: Optional[int] = None) -> Tuple[dict, np.ndarray]:
        for index, remote in enumerate(self._remotes):
            remote.send(("reset", None if seed is None else seed + index))
        results = [remote.recv() for remote in self._remotes]
        return self._stack([r[0] for r in results]), np.stack([r[1] for r in results])

    def step(self, actions) -> Tuple[dict, np.ndarray, np.ndarray, np.ndarray, List[dict]]:
        for remote, action in zip(self._remotes, np.asarray(actions).tolist()):
            remote.send(("step", int(action)))
        results = [remote.recv() for remote in self._remotes]
        observations = self._stack([r[0] for r in results])
        masks = np.stack([r[1] for r in results])
        rewards = np.array([r[2] for r in results], dtype=np.float32)
        dones = np.array([r[3] for r in results], dtype=bool)
        infos = [r[4] for r in results]
        return observations, masks, rewards, dones, infos

    @staticmethod
    def _stack(observations: List[dict]) -> Dict[str, np.ndarray]:
        return {
            "planes": np.stack([o["planes"] for o in observations]),
            "scalars": np.stack([o["scalars"] for o in observations]),
        }

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for remote in self._remotes:
            try:
                remote.send(("close", None))
            except (BrokenPipeError, OSError):
                pass
        for process in self._workers:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()

    def __enter__(self) -> "VecClashEnv":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def benchmark(num_envs: int = 8, steps: int = 400) -> None:
    """Measure real throughput; the useful number is env-steps per second."""
    import time

    rng = np.random.default_rng(0)
    with VecClashEnv(num_envs=num_envs) as vec:
        _, masks = vec.reset()
        started = time.perf_counter()
        finished = 0
        for _ in range(steps):
            actions = []
            for mask in masks:
                legal = np.flatnonzero(mask)
                actions.append(0 if rng.random() < 0.7 else int(rng.choice(legal)))
            _, masks, _, dones, infos = vec.step(actions)
            finished += int(dones.sum())
        elapsed = time.perf_counter() - started
        total = steps * num_envs
        print(f"{num_envs} envs: {total} steps in {elapsed:.1f}s "
              f"-> {total / elapsed:,.0f} steps/s, {finished} episodes finished")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark the vectorised env")
    parser.add_argument("--envs", type=int, default=8)
    parser.add_argument("--steps", type=int, default=400)
    args = parser.parse_args()
    benchmark(args.envs, args.steps)
