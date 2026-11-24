"""League learner: two brains that both learn, by PPO, from fighting each other.

    .venvs\\buildabot\\Scripts\\python.exe tools\\league\\learner.py --name league_v4 --actors 2

* "hog": starts from runs/selfplay/sp_v1/it020.pt (replay imitation -> Hog
  fine-tune -> PPO); always plays the owner's Hog 2.6 with its real forms.
* "gen": starts from runs/tokens/rs_big/best.pt (imitation on all replays);
  pilots ladder decks with their real forms, against Hog and against itself.

Each brain trains on its own seats' decisions. A share of games is played
against a frozen past snapshot of the general brain (every --snapshot-every
updates; the parents stay in each pool for good) so neither forgets how to
beat old play. A KL penalty to each brain's own parent keeps early training
near human play and decays.

Stop: create runs/league/<name>/STOP. Resume: run the same command again.
Nothing here touches the emulator.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
PY = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe" if os.name == "nt" else Path(sys.executable)
PARENTS = {"hog": ROOT / "runs/selfplay/sp_v1/it020.pt",
           "gen": ROOT / "runs/tokens/rs_big/best.pt",
           # A second, independent general lineage: imitation on the current
           # engine's rows (pipeline_v3), so the opponents are not all one model.
           "gen2": ROOT / "runs/pipeline_v3/general/best.pt"}


def save(net, path, version, meta):
    import torch
    tmp = path.with_suffix(".tmp")
    torch.save({"model": {k: v.detach().cpu() for k, v in net.state_dict().items()},
                "meta": meta, "version": version}, tmp)
    os.replace(tmp, path)


def init_from(run, src, obs_v):
    """Continue another league run under a newer observation version: each
    brain's latest weights (and its original parent, the KL reference) are
    upgraded with league.model.from_league; the source pools come along."""
    from league.model import from_league
    shutil.copy(src / "vocab.json", run / "vocab.json")
    for tag in [t for t in ("hog", "gen", "gen2") if (src / t / "latest.pt").exists()]:
        d = run / tag
        (d / "pool").mkdir(parents=True, exist_ok=True)
        net, meta, version = from_league(src / tag / "latest.pt", obs_v)
        save(net, d / "latest.pt", version, meta)
        ref, _, _ = from_league(src / tag / "parent.pt", obs_v)
        save(ref, d / "parent.pt", 0, meta)
        for p in sorted((src / tag / "pool").glob("*.pt")):
            snap, _, v = from_league(p, obs_v)
            save(snap, d / "pool" / p.name, v, meta)
        (d / "meta.json").write_text(json.dumps(meta))


def add_brain(run, tag, obs_v):
    """A new learning brain in an existing run, from its imitation parent."""
    import rs_rows as RR
    from league.model import from_parent
    from rs_eval import _unit_names
    royalesim, _, _, cat = RR._setup()
    names = _unit_names()
    net = from_parent(PARENTS[tag], names, len(cat), obs_v=obs_v)
    meta = dict(n_cards=len(cat) + 2, n_units=len(names) + 2, d=net.cls.shape[-1],
                layers=len(net.encoder.layers), heads=net.encoder.layers[0].self_attn.num_heads,
                parent=str(PARENTS[tag]), league=True, brain=tag, obs_v=obs_v)
    d = run / tag
    (d / "pool").mkdir(parents=True, exist_ok=True)
    save(net, d / "latest.pt", 0, meta)
    save(net, d / "parent.pt", 0, meta)
    shutil.copy(d / "latest.pt", d / "pool" / "000000.pt")
    (d / "meta.json").write_text(json.dumps(meta))


def init_run(run):
    import rs_rows as RR
    from league.model import from_parent
    from rs_eval import _unit_names
    royalesim, _, _, cat = RR._setup()
    names = _unit_names()
    (run / "vocab.json").write_text(json.dumps(
        {"engine_units": names, "units": {n: i + 2 for i, n in enumerate(names)}}))
    for tag, parent in PARENTS.items():
        net = from_parent(parent, names, len(cat))
        meta = dict(n_cards=len(cat) + 2, n_units=len(names) + 2, d=net.cls.shape[-1],
                    layers=len(net.encoder.layers), heads=net.encoder.layers[0].self_attn.num_heads,
                    parent=str(parent), league=True, brain=tag, obs_v=2)
        d = run / tag
        (d / "pool").mkdir(parents=True, exist_ok=True)
        save(net, d / "latest.pt", 0, meta)
        save(net, d / "parent.pt", 0, meta)
        shutil.copy(d / "latest.pt", d / "pool" / "000000.pt")
        (d / "meta.json").write_text(json.dumps(meta))


# HASTY_NEWCOL_BOOST=k (2026-11-23, UNVERIFIED k): the inputs added at zero weight
# for obs_v 7 (unit features 7-17, absolute tower hp, pred_scale, spell_type) take
# k Adam steps per step instead of 1. Measured on v80: those weights are about 10x
# smaller than the original inputs' and close to the most Adam can move them at
# lr 5e-6 in v80's ~12k steps, so they were limited by the step size.
NEWCOL_BOOST = float(os.environ.get("HASTY_NEWCOL_BOOST", "1"))


class Trainer:
    def _boost_new_inputs(self, opt):
        torch = self.torch
        m = self.model
        targets = []
        if hasattr(m, "unit_in") and m.unit_in.weight.shape[1] > 7:
            mk = torch.zeros_like(m.unit_in.weight); mk[:, 7:] = 1
            targets.append((m.unit_in.weight, mk))
        if hasattr(m, "state_in") and m.state_in.weight.shape[1] == 17:
            mk = torch.zeros_like(m.state_in.weight); mk[:, 6:12] = 1
            targets.append((m.state_in.weight, mk))
        for name in ("pred_scale", "spell_type"):
            p = getattr(m, name, None)
            if p is not None:
                targets.append((p, torch.ones_like(p)))
        g = opt.param_groups[0]
        b1, b2 = g["betas"]
        with torch.no_grad():
            for p, mk in targets:
                st = opt.state.get(p)
                if not st or "exp_avg" not in st:
                    continue
                n = float(st["step"])
                mh = st["exp_avg"] / (1 - b1 ** n)
                vh = st["exp_avg_sq"] / (1 - b2 ** n)
                p.sub_((NEWCOL_BOOST - 1) * g["lr"] * mk * mh / (vh.sqrt() + g["eps"]))

    def __init__(self, run, tag, args, dev):
        import torch
        from league.model import LeaguePolicy
        self.torch, self.tag, self.args, self.dev = torch, tag, args, dev
        self.dir = run / tag
        self.meta = json.loads((self.dir / "meta.json").read_text())
        m = self.meta

        def load(path):
            blob = torch.load(path, map_location="cpu", weights_only=False)
            net = LeaguePolicy(m["n_cards"], m["n_units"], d=m["d"], layers=m["layers"], heads=m["heads"], obs_v=m.get("obs_v", 1))
            net.load_state_dict(blob["model"])
            return net.to(dev).eval(), blob.get("version", 0)

        self.model, self.version = load(self.dir / "latest.pt")
        # KL reference: the imitation parent by default; a gated run passes
        # --kl-ref champion.pt (anchoring to the imitation parent undid a run in
        # October: the anchor pulled the policy back to what it started from).
        ref_path = self.dir / args.kl_ref
        self.ref, _ = load(ref_path if ref_path.exists() else self.dir / "parent.pt")
        # Imitation step after each PPO update (--il-dir: rows_*.npz from
        # engine_bc.py --collect-only, winning human games of the deck).
        self.il_files = sorted(Path(args.il_dir).glob("rows_*.npz")) if args.il_dir else []
        if args.il_dir and not self.il_files:
            raise RuntimeError(f"--il-dir {args.il_dir} has no rows_*.npz")
        self.il_rng = np.random.default_rng()
        self.opt = torch.optim.AdamW(self.model.parameters(), lr=args.lr, weight_decay=0.0)
        if (self.dir / "opt.pt").exists():
            self.opt.load_state_dict(torch.load(self.dir / "opt.pt", map_location=dev))
        self.pending = []
        self.t_last = time.time()

    def add(self, d):
        keep = d["version"] >= self.version - self.args.max_lag
        if keep.any():
            self.pending.append({k: v[keep] for k, v in d.items()})

    def ready(self):
        return sum(len(p["a"]) for p in self.pending) >= self.args.rows

    def update(self):
        torch, args, dev = self.torch, self.args, self.dev
        import torch.nn.functional as F
        from league.model import gate_logq
        from league.obs import KEYS
        from league.actor import DECIDE, TILE_EXPLORE
        d = {k: np.concatenate([p[k] for p in self.pending]) for k in self.pending[0]}
        self.pending = []
        N = len(d["a"])
        adv = d["adv"].astype(np.float32)
        adv = (adv - adv.mean()) / (adv.std() + 1e-6)
        v = self.version
        kl_coef = args.kl1 + (args.kl0 - args.kl1) * max(0.0, 1 - v / args.kl_decay_updates)
        model, ref, opt = self.model, self.ref, self.opt
        stats, stopped = [], False
        for _ in range(args.epochs):
            if stopped:
                break
            perm = np.random.permutation(N)
            for i in range(0, N, args.batch):
                idx = perm[i:i + args.batch]
                from league.obs import trim
                b = trim({k: torch.as_tensor(d[k][idx]).to(dev) for k in KEYS})
                mask = torch.as_tensor(d["mask"][idx]).to(dev)
                a = torch.as_tensor(d["a"][idx]).long().to(dev)
                old = torch.as_tensor(d["logp"][idx]).float().to(dev)
                A = torch.as_tensor(adv[idx]).to(dev)
                R = torch.as_tensor(d["ret"][idx]).float().to(dev)
                tile = torch.as_tensor(d["tile"][idx]).long().to(dev)
                tm = torch.as_tensor(np.unpackbits(d["tmask"][idx], axis=1)[:, :576].astype(bool)).to(dev)
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    gate, cls, val = model.heads(b)
                    slot = (a - 1).clamp(0, 3)
                    card = b["hand"].gather(1, slot[:, None])[:, 0]
                    tl = model.tile_logits(cls, card)
                    with torch.no_grad():
                        rgate, rcls, _ = ref.heads(b)
                        rtl = ref.tile_logits(rcls, card) if args.tile_kl > 0 else None
                if args.card_temp > 0:                                            # split decoding
                    from league.model import split_logq
                    lq = split_logq(gate, mask, DECIDE, args.gate_temp, args.card_temp)
                    lq_ref = split_logq(rgate, mask, DECIDE, args.gate_temp, args.card_temp)
                else:
                    lq = gate_logq(gate.float() / args.gate_temp, mask, DECIDE)   # as the actors sampled it
                    lq_ref = gate_logq(rgate.float() / args.gate_temp, mask, DECIDE)
                new = lq.gather(1, a[:, None])[:, 0]
                played = tile >= 0
                pt = F.softmax((tl.float() / args.tile_temp).masked_fill(~tm, -1e9), 1)   # as the actors sampled
                nleg = tm.float().sum(1, keepdim=True).clamp(min=1)
                pt = (1 - TILE_EXPLORE) * pt + TILE_EXPLORE * tm.float() / nleg
                lt = pt.gather(1, tile.clamp(min=0)[:, None])[:, 0].clamp(min=1e-12).log()
                new = new + torch.where(played, lt, torch.zeros_like(lt))
                ratio = (new - old).exp()
                pg = -torch.min(ratio * A, ratio.clamp(1 - args.clip, 1 + args.clip) * A).mean()
                p = lq.exp()
                ent = -(p * lq.masked_fill(~mask, 0)).sum(1).mean()
                kl = (p * (lq - lq_ref).masked_fill(~mask, 0)).sum(1).mean()
                v_loss = F.smooth_l1_loss(val.float(), R)
                # Warm-up: a fresh value head first, so the first policy steps
                # follow advantages rather than its noise.
                if rtl is not None:
                    # Placement anchor (2026-11-22, Codex review): the gate KL above does not
                    # cover the tile head, so placements could drift freely. KL(new || ref)
                    # over legal tiles, on rows where a card was played. UNVERIFIED weight.
                    lpt = F.log_softmax((tl.float() / args.tile_temp).masked_fill(~tm, -1e9), 1)
                    lpr = F.log_softmax((rtl.float() / args.tile_temp).masked_fill(~tm, -1e9), 1)
                    tkl = (lpt.exp() * (lpt - lpr)).masked_fill(~tm, 0).sum(1)
                    tkl = (tkl * played).sum() / played.sum().clamp(min=1)
                    kl = kl + args.tile_kl * tkl
                loss = v_loss if v < args.warmup else pg + 0.5 * v_loss - args.ent * ent + kl_coef * kl
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                if NEWCOL_BOOST > 1:
                    self._boost_new_inputs(opt)
                with torch.no_grad():
                    approx_kl = ((ratio - 1) - (new - old)).mean().item()
                stats.append((pg.item(), v_loss.item(), ent.item(), kl.item(),
                              (ratio - 1).abs().mean().item(), approx_kl))
                kls = [x[5] for x in stats[-8:]]
                if v >= args.warmup and len(kls) >= 4 and np.mean(kls) > args.target_kl:
                    stopped = True
                    break
        il = self.imitate() if (self.il_files and self.tag == "hog" and v >= args.warmup) else None
        self.version += 1
        save(model, self.dir / "latest.pt", self.version, self.meta)
        if self.version % args.snapshot_every == 0:
            shutil.copy(self.dir / "latest.pt", self.dir / "pool" / f"{self.version:06d}.pt")
            torch.save(opt.state_dict(), self.dir / "opt.pt")
            if args.pool_keep > 0:
                # Disk cap (owner 2026-11-07): the parent (first file) stays,
                # plus the newest --pool-keep snapshots.
                snaps = sorted((self.dir / "pool").glob("*.pt"))
                for old in snaps[1:-args.pool_keep]:
                    old.unlink(missing_ok=True)
        s = np.mean(stats, 0)
        rec = dict(brain=self.tag, update=self.version, rows=N, pg=round(s[0], 4),
                   v_loss=round(s[1], 4), entropy=round(s[2], 3), kl_parent=round(s[3], 4),
                   ratio_dev=round(s[4], 4), approx_kl=round(s[5], 4), steps=len(stats),
                   kl_coef=round(kl_coef, 4), act_rate=round(float((d["a"] > 0).mean()), 4),
                   button_rate=round(float((d["a"] >= 5).mean()), 5),
                   seconds=round(time.time() - self.t_last, 1))
        if il is not None:
            rec.update(il_nll=round(il[0], 4), il_tile_ce=round(il[1], 3))
        self.t_last = time.time()
        return rec

    def imitate(self):
        """--il-steps gradient steps of imitation on human rows, loss weight --il-w.
        Same loss as engine_bc.train without its KL term: gate NLL / 5 (waits were
        subsampled to WAIT_KEEP, so weighted back) + tile cross-entropy. The gate is
        scored at temperature 1, as the rows' model was trained."""
        torch, args, dev = self.torch, self.args, self.dev
        import torch.nn.functional as F
        from league.model import gate_logq
        from league.obs import KEYS, trim
        from league.actor import DECIDE
        from league.engine_bc import WAIT_KEEP
        out = []
        for _ in range(args.il_steps):
            f = self.il_files[int(self.il_rng.integers(len(self.il_files)))]
            try:
                d = dict(np.load(f))
            except Exception:
                continue
            idx = self.il_rng.permutation(len(d["a"]))[:args.batch]
            b = trim({k: torch.as_tensor(d[k][idx]).to(dev) for k in KEYS})
            mask = torch.as_tensor(d["mask"][idx]).to(dev)
            a = torch.as_tensor(d["a"][idx]).long().to(dev)
            tile = torch.as_tensor(d["tile"][idx]).long().to(dev)
            tm = torch.as_tensor(np.unpackbits(d["tmask"][idx], axis=1)[:, :576].astype(bool)).to(dev)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                gate, cls, _ = self.model.heads(b)
            g = gate.float()
            if self.meta.get("wait_shift"):
                # The model's wait bias was lowered so that it plays near-greedy
                # (calibrate_wait.py). Human rows are scored with the shift taken
                # out, or imitation would pull the bias straight back.
                g = torch.cat([g[:, :1] + float(self.meta["wait_shift"]), g[:, 1:]], 1)
            lq = gate_logq(g, mask, DECIDE)
            nll = -lq.gather(1, a[:, None])[:, 0]
            nll = (nll * torch.where(a == 0, 1.0 / WAIT_KEEP, 1.0)).mean()
            played = (a >= 1) & (a <= 4) & (tile >= 0)
            tl_loss = torch.zeros((), device=dev)
            if played.any():
                card = b["hand"][played].gather(1, (a[played] - 1).clamp(0, 3)[:, None])[:, 0]
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    tl = self.model.tile_logits(cls[played], card).float()
                tl_loss = F.cross_entropy(tl.masked_fill(~tm[played], -1e9), tile[played])
            loss = args.il_w * (nll / 5 + tl_loss)
            self.opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.opt.step()
            out.append((nll.item(), tl_loss.item()))
        return tuple(np.mean(out, 0)) if out else None

    def close(self):
        self.torch.save(self.opt.state_dict(), self.dir / "opt.pt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="league_v4")
    ap.add_argument("--actors", type=int, default=2)
    ap.add_argument("--envs", type=int, default=128)
    ap.add_argument("--rows", type=int, default=300_000, help="decisions per update")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--clip", type=float, default=0.2)
    ap.add_argument("--target-kl", type=float, default=0.015,
                    help="stop the update when the running approx KL passes this")
    ap.add_argument("--ent", type=float, default=0.003)
    ap.add_argument("--kl0", type=float, default=0.05)
    ap.add_argument("--kl1", type=float, default=0.003)
    ap.add_argument("--kl-decay-updates", type=int, default=3000)
    ap.add_argument("--snapshot-every", type=int, default=10)
    ap.add_argument("--max-lag", type=int, default=1, help="drop rows this many versions old")
    ap.add_argument("--warmup", type=int, default=15, help="first updates train the value head only")
    ap.add_argument("--gpu-frac", type=float, default=0.45)
    ap.add_argument("--init-from", default="", help="continue this league run (its latest weights)")
    ap.add_argument("--obs-v", type=int, default=3)
    ap.add_argument("--add-gen2", action="store_true", help="add the second general brain to this run")
    ap.add_argument("--focus-parent", default="",
                    help="with --init-from: a new focus brain from this imitation checkpoint "
                         "(the opponents' brains come from the source run)")
    ap.add_argument("--focus-deck", default="", help="JSON file copied to the run as focus_deck.json")
    ap.add_argument("--learn", default="hog,gen,gen2", help="brains that learn; the rest are frozen opponents")
    ap.add_argument("--opp-gate-temp", type=float, default=1.0, help="gate temperature of frozen opponents")
    ap.add_argument("--hog-share", type=float, default=0.85, help="share of games with the focus (hog) brain")
    ap.add_argument("--tile-kl", type=float, default=0.0,
                    help="weight of the tile-placement KL to the reference, added to the gate KL")
    ap.add_argument("--shape-w", type=float, default=1.0,
                    help="weight of the tower/crown shaping reward against the +-1 result")
    ap.add_argument("--card-temp", type=float, default=0.0,
                    help="split decoding: card/button temperature; play-or-wait at --gate-temp (0 = one gate temperature)")
    ap.add_argument("--gate-temp", type=float, default=1.0,
                    help="play/wait gate temperature for rollouts and the loss (live plays at 0.1)")
    ap.add_argument("--hog-level", type=int, default=16, help="card level of the focus seat (owner's live level)")
    ap.add_argument("--crforge", action="store_true",
                    help="actors play in crforge (crforgesim.CrforgeBattle); experiment 2026-11-21")
    ap.add_argument("--real", action="store_true",
                    help="actors play in the real engine (realsim.RealBattle; spawn starts are dropped)")
    ap.add_argument("--blind-share", type=float, default=0.0, help="actor: reader noise, one unseen enemy card")
    ap.add_argument("--drop-body", type=float, default=0.0, help="actor: reader noise, single unseen bodies")
    ap.add_argument("--idle-w", type=float, default=0.0, help="actor: penalty per threat unanswered 4 s")
    ap.add_argument("--idle-threat", type=float, default=3.0, help="actor: elixir that counts as a threat")
    ap.add_argument("--style-share", type=float, default=0.0, help="actor: share of styled Hog opponents")
    ap.add_argument("--pool-keep", type=int, default=0, help="keep only the parent + newest N snapshots (0 = all)")
    ap.add_argument("--tile-temp", type=float, default=1.0,
                    help="tile temperature for rollouts and the loss (the live bot takes the best tile)")
    ap.add_argument("--tower-start", type=float, default=None,
                    help="actor: share of games starting mid-match with towers down (actor default 0.5)")
    ap.add_argument("--threat-start", type=float, default=None,
                    help="actor: share of focus games starting with enemy troops at the bridge (actor default 0.2)")
    ap.add_argument("--drill-share", type=float, default=0.0, help="actor: share of focus games that are drills")
    ap.add_argument("--drill-ticks", type=int, default=300, help="actor: drill length in ticks")
    ap.add_argument("--drill-hp-scale", type=float, default=1000.0, help="actor: drill tower hp per -1 of score")
    ap.add_argument("--drill-elixir-w", type=float, default=0.06, help="actor: drill score cost per elixir")
    ap.add_argument("--kl-ref", default="parent.pt",
                    help="file in the brain's folder the KL penalty anchors to (gated runs: champion.pt)")
    ap.add_argument("--il-dir", default="", help="imitation rows (engine_bc --collect-only output) for the focus brain")
    ap.add_argument("--il-w", type=float, default=0.2, help="weight of the imitation loss")
    ap.add_argument("--il-steps", type=int, default=1, help="imitation gradient steps after each PPO update")
    ap.add_argument("--opp-shares", default="", help="actor: focus opponents' shares il,gen,snap (e.g. 0.4,0.4,0.2)")
    ap.add_argument("--opp-il", default="", help="actor: frozen imitation checkpoint")
    ap.add_argument("--opp-gen", default="", help="actor: frozen best general checkpoint")
    ap.add_argument("--opp-il-temp", type=float, default=1.0, help="actor: gate temperature of the imitation opponent")
    ap.add_argument("--deck-shares", default="", help="actor: opponent decks' shares common,worst,pool (e.g. 0.3,0.3,0.4)")
    ap.add_argument("--ghosts", default="", help="actor: ghost opponents (ghost_prep.py output)")
    ap.add_argument("--ghost-share", type=float, default=0.0, help="actor: share of new matches that start a ghost group")
    ap.add_argument("--ghost-tries", type=int, default=4, help="actor: tries per ghost, scored against each other")
    ap.add_argument("--ghost-win", type=float, default=0.0, help="actor: ghost score per game result (+1/-1)")
    ap.add_argument("--ghost-pfsp", type=float, default=0.0, help="actor: share of ghost groups drawn by deck difficulty")
    ap.add_argument("--ghost-attack", type=float, default=0.0, help="actor: weight of damage dealt in the ghost score")
    ap.add_argument("--ghost-crown", type=float, default=0.0, help="actor: ghost score per tower destroyed")
    ap.add_argument("--ghost-leak", type=float, default=0.0, help="actor: ghost score cost of time at full elixir")
    ap.add_argument("--ghost-idle", type=float, default=0.0, help="actor: share of idle or thinned ghosts")
    ap.add_argument("--init-only", action="store_true", help="build the run's brains and exit (e.g. for button_bc)")
    args = ap.parse_args()

    import torch
    run = ROOT / "runs" / "league" / args.name
    run.mkdir(parents=True, exist_ok=True)
    if not (run / "hog" / "latest.pt").exists():
        if args.init_from:
            init_from(run, ROOT / "runs" / "league" / args.init_from, args.obs_v)
            if args.focus_parent:
                shutil.rmtree(run / "hog")
                PARENTS["hog"] = ROOT / args.focus_parent
                add_brain(run, "hog", args.obs_v)
        else:
            init_run(run)
    if args.focus_deck:
        shutil.copy(ROOT / args.focus_deck, run / "focus_deck.json")
    if args.init_only:
        return
    (run / "STOP").unlink(missing_ok=True)
    (run / "args.json").write_text(json.dumps(vars(args)))
    dev = "cuda"
    torch.cuda.set_per_process_memory_fraction(args.gpu_frac)
    if args.add_gen2 and not (run / "gen2" / "latest.pt").exists():
        add_brain(run, "gen2", args.obs_v)
    if args.il_dir:
        args.il_dir = str(ROOT / args.il_dir)
    trainers = {t: Trainer(run, t, args, dev) for t in ("hog", "gen", "gen2") if t in args.learn.split(",")
                if (run / t / "latest.pt").exists()}

    actors = []
    logs = run / "logs"
    logs.mkdir(exist_ok=True)
    for k in range(args.actors):
        f = (logs / f"actor{k}.log").open("a")
        actors.append(subprocess.Popen(
            [str(PY), str(ROOT / "tools/league/actor.py"), "--run", str(run), "--actor", str(k),
             "--envs", str(args.envs), "--seed", str(int(time.time()) % 100000 * 10 + k)]
            + (["--real"] if args.real else []) + (["--crforge"] if args.crforge else []) + ["--hog-level", str(args.hog_level),
                                                    "--train-gate-temp", str(args.gate_temp),
                                                    "--train-card-temp", str(args.card_temp),
                                                    "--train-tile-temp", str(args.tile_temp),
                                                    "--shape-w", str(args.shape_w),
                                                    "--learn", args.learn, "--opp-gate-temp", str(args.opp_gate_temp),
                                                    "--hog-share", str(args.hog_share),
                                                    "--blind-share", str(args.blind_share),
                                                    "--drop-body", str(args.drop_body),
                                                    "--idle-w", str(args.idle_w),
                                                    "--idle-threat", str(args.idle_threat),
                                                    "--style-share", str(args.style_share)]
            + (["--opp-shares", args.opp_shares, "--opp-il", str(ROOT / args.opp_il),
                "--opp-gen", str(ROOT / args.opp_gen), "--opp-il-temp", str(args.opp_il_temp)]
               if args.opp_shares else [])
            + (["--deck-shares", args.deck_shares] if args.deck_shares else [])
            + (["--ghosts", args.ghosts, "--ghost-share", str(args.ghost_share),
                "--ghost-tries", str(args.ghost_tries), "--ghost-attack", str(args.ghost_attack), "--ghost-crown", str(args.ghost_crown),
                "--ghost-leak", str(args.ghost_leak), "--ghost-idle", str(args.ghost_idle),
                "--ghost-win", str(args.ghost_win), "--ghost-pfsp", str(args.ghost_pfsp)] if args.ghosts else [])
            + (["--tower-start", str(args.tower_start)] if args.tower_start is not None else [])
            + (["--threat-start", str(args.threat_start)] if args.threat_start is not None else [])
            + (["--drill-share", str(args.drill_share), "--drill-ticks", str(args.drill_ticks),
                "--drill-hp-scale", str(args.drill_hp_scale), "--drill-elixir-w", str(args.drill_elixir_w)]
               if args.drill_share > 0 else []),
            stdout=f, stderr=subprocess.STDOUT, cwd=ROOT,
            # HASTY_GPUS=N (rented multi-GPU machine): spread actors over N GPUs, actor k on
            # GPU k % N. Unset keeps every actor on the default GPU, as before.
            env=(dict(os.environ, CUDA_VISIBLE_DEVICES=str(k % int(os.environ["HASTY_GPUS"])))
                 if os.environ.get("HASTY_GPUS") else None)))
    roll = run / "rollouts"
    roll.mkdir(exist_ok=True)
    log = run / "log.jsonl"
    try:
        while not (run / "STOP").exists():
            for k, p in enumerate(actors):
                if p.poll() is not None:
                    raise RuntimeError(f"actor {k} exited ({p.returncode}); see {logs / f'actor{k}.log'}")
            got = False
            for f in sorted(roll.glob("a*_*.npz"), key=lambda p: p.stat().st_mtime):
                tag = f.stem.split("_")[1]
                try:
                    with np.load(f) as z:
                        d = {k: z[k] for k in z.files}
                except Exception:
                    continue
                f.unlink()
                if tag in trainers:
                    trainers[tag].add(d)
                    got = True
            did = False
            for t in trainers.values():
                if t.ready():
                    rec = t.update()
                    act = []
                    for st in roll.glob("stats_a*.json"):
                        try:
                            act.append(json.loads(st.read_text()))
                        except ValueError:
                            pass
                    tot = lambda k: sum(x.get(k, 0) for x in act)
                    rec.update(matches_total=tot("matches"), matches_per_s=round(tot("matches_per_s"), 2),
                               hog_vs_gen=f"{tot('vs_gen_wins')}/{tot('vs_gen_games')}",
                               hog_vs_snap=f"{tot('vs_snap_wins')}/{tot('vs_snap_games')}",
                               hog_vs_il=f"{tot('vs_il_wins')}/{tot('vs_il_games')}")
                    with log.open("a") as fh:
                        fh.write(json.dumps(rec) + "\n")
                    print(json.dumps(rec), flush=True)
                    did = True
            if not got and not did:
                time.sleep(2)
    finally:
        (run / "STOP").touch()
        for p in actors:
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                p.kill()
        for t in trainers.values():
            t.close()
        (run / "STOP").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
