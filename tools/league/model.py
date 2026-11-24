"""League policy: the imitation TokenPolicy plus velocity, ability buttons and
a return-value head. Built from an imitation / PPO checkpoint so it starts
from everything those learned.

Gate logits: [wait, slot 0..3, button 0..1]. The button logits start at -6,
so a fresh model behaves exactly like its parent until training finds a use
for them. New unit-feature columns (vx, vy) start at zero weight for the same
reason.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn

from sim.model_tokens import TILES, TokenPolicy

from .obs import N_BUTTONS, UF

N_GATE = 1 + 4 + N_BUTTONS


class LeaguePolicy(TokenPolicy):
    """obs_v 1: league_v1..v4. obs_v 2 adds the opponent's counted elixir (a
    fifth scalar) and N_PRED predicted-card tokens from the ladder deck table."""

    def __init__(self, n_cards, n_units, d=256, layers=6, heads=8, obs_v=1):
        self.uf = UF if obs_v >= 6 else 12 if obs_v >= 5 else 10 if obs_v >= 4 else 9
        super().__init__(n_cards, n_units, d=d, layers=layers, heads=heads, unit_features=self.uf)
        self.obs_v = obs_v
        self.type_emb = nn.Embedding(7, d)               # + ability token
        if obs_v >= 2:
            # obs_v 7: 12 tower values (fractions in the model's frame + absolute hit points).
            self.state_in = nn.Linear((12 if obs_v >= 7 else 6) + 5, d)
            self.pred_in = nn.Linear(d, d)
            # Predicted-card tokens start silent (scale 0): a fresh model plays
            # exactly like its parent until training finds them useful.
            self.pred_scale = nn.Parameter(torch.zeros(()))
        if obs_v >= 3:
            from .obs import SF
            # Spells in flight: padding unless a spell is live, so a model
            # converted from an obs_v 2 one plays the same in their absence.
            self.spell_in = nn.Linear(SF, d)
            self.spell_type = nn.Parameter(torch.zeros(d))
        self.abil_in = nn.Linear(5 * N_BUTTONS, d)
        self.button_head = nn.Linear(d, N_BUTTONS)
        self.ret_head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))

    def encode(self, b):
        n = b["unit_ids"].shape[0]
        dev = b["unit_ids"].device
        t = lambda i: self.type_emb.weight[i]
        uf = b["unit_feats"][..., :self.uf]
        if self.obs_v < 4:
            # Before obs_v 4 the deploy flag was always 0 (live could not read it).
            uf = torch.cat([uf[..., :6], torch.zeros_like(uf[..., 6:7]), uf[..., 7:]], -1)
        units = self.unit_emb(b["unit_ids"]) + self.unit_in(uf) + t(1)
        sc = b["scalars"] if self.obs_v >= 2 else b["scalars"][:, :4]
        state = self.state_in(torch.cat([b["towers"], sc], -1))[:, None] + t(2)
        if self.obs_v >= 2:
            # Predicted unseen opponent cards, folded into the state token as
            # a probability-weighted card embedding. Separate tokens (the first
            # try) added attention slots and moved the parent's play even at
            # zero scale: Hog 30% -> 20% before any training.
            pe = (self.card_emb(b["pred"]) * b["pred_p"][..., None]).sum(1)
            state = state + (self.pred_in(pe) * self.pred_scale)[:, None]
        abil = self.abil_in(b["abil"])[:, None] + t(6)
        hand = self.card_emb(b["hand"]) + self.slot_emb.weight[None] + t(3)
        nxt = self.card_emb(b["next"])[:, None] + t(4)
        seen = self.card_emb(b["opp_seen"]) + t(5)
        last = self.card_emb(b["opp_last"]) + self.age_in(b["opp_last_age"][..., None]) + t(5)
        cls = self.cls.expand(n, -1, -1) + t(0)
        # Same token order as TokenPolicy, with the ability token appended, so
        # hand tokens stay at 2:6 for the card pointer.
        parts = [cls, state, hand, nxt, units, seen, last, abil]
        masks = [torch.zeros(n, 2, dtype=torch.bool, device=dev),
                 b["hand"] == 0, b["next"][:, None] == 0, b["unit_ids"] == 0,
                 b["opp_seen"] == 0, b["opp_last"] == 0,
                 torch.zeros(n, 1, dtype=torch.bool, device=dev)]
        if self.obs_v >= 3:
            sp = self.card_emb(b["spell_ids"]) + self.spell_in(b["spell_feats"]) + self.spell_type
            parts.append(sp)
            masks.append(b["spell_ids"] == 0)
        x = torch.cat(parts, 1)
        pad = torch.cat(masks, 1)
        h = self.norm(self.encoder(x, src_key_padding_mask=pad))
        return h[:, 0], h[:, 2:6]

    def heads(self, b):
        """Gate logits [N, 7], the encoded cls (for the tile head), return value [N]."""
        cls, hand_h = self.encode(b)
        q = self.card_query(cls)
        slot = torch.einsum("nd,nkd->nk", q, hand_h) / hand_h.shape[-1] ** 0.5
        slot = slot.masked_fill(b["hand"] == 0, -1e4)
        gate = torch.cat([self.wait_head(cls), slot, self.button_head(cls)], 1)
        # The value head reads a detached trunk: a fresh head's large early
        # errors otherwise train the pretrained encoder and wreck the policy
        # (league_v1 update 2: Hog seat 25% -> 1% against its own parent).
        return gate, cls, self.ret_head(cls.detach())[:, 0]

    def tile_logits(self, cls, card_ids):
        return self.tile_head(torch.cat([cls, self.card_emb(card_ids)], -1))


def gate_logq(gate, mask, decide):
    """Log-probabilities of [wait, slots, buttons] as the agent samples them.

    The parent's semantics, kept so a fresh model plays exactly like it: with
    p = softmax(gate), wait with probability p_wait ** (decide / 20) - the same
    wait rate per second at any decision cadence - otherwise act, choosing
    among the allowed actions in proportion to p.
    """
    g = gate.float().masked_fill(~mask, -1e9)
    lp = torch.log_softmax(g, 1)
    lw = lp[:, 0] * (decide / 20)
    lw = torch.where(mask[:, 1:].any(1), lw, torch.zeros_like(lw))
    l_act = torch.log1p(-lw.exp().clamp(max=1 - 1e-6))
    la = torch.log_softmax(g[:, 1:], 1) + l_act[:, None]
    return torch.cat([lw[:, None], la], 1).masked_fill(~mask, -1e9)


def from_league(path, obs_v=3):
    """A league checkpoint upgraded to a later observation version: every
    existing weight kept, new parts at their silent initial values."""
    blob = torch.load(path, map_location="cpu", weights_only=False)
    m = blob["meta"]
    net = LeaguePolicy(m["n_cards"], m["n_units"], d=m["d"], layers=m["layers"], heads=m["heads"], obs_v=obs_v)
    sd = dict(blob["model"])
    w = sd.get("unit_in.weight")
    if w is not None and w.shape[1] < net.uf:
        # New unit features start at zero weight.
        grown = torch.zeros(w.shape[0], net.uf)
        grown[:, :w.shape[1]] = w
        sd["unit_in.weight"] = grown
    w = sd.get("state_in.weight")
    if w is not None and w.shape[1] == 11 and obs_v >= 7:
        # [6 towers, 5 scalars] -> [6 towers, 6 absolute hit points at zero weight, 5 scalars]
        grown = torch.zeros(w.shape[0], 17)
        grown[:, :6], grown[:, 12:] = w[:, :6], w[:, 6:]
        sd["state_in.weight"] = grown
    missing, unexpected = net.load_state_dict(sd, strict=False)
    assert not unexpected, unexpected
    assert all(k.startswith("spell_") for k in missing), missing
    return net, dict(m, obs_v=obs_v), blob.get("version", 0)


def from_parent(path, unit_names, n_catalogue, wait_keep=0.25, obs_v=2):
    """A LeaguePolicy carrying `path`'s weights, vocabulary remapped by name.

    `unit_names`: the installed engine's unit types; token = index + 2.
    `n_catalogue`: the installed engine's card count; token = index + 2.
    The parent's wait logit was trained on waits subsampled to `wait_keep`;
    that correction goes into the wait bias. The decision cadence is handled
    by `gate_logq`.
    """
    blob = torch.load(path, map_location="cpu", weights_only=False)
    meta, sd = blob["meta"], blob["model"]
    d, layers, heads = meta.get("d", 192), meta.get("layers", 4), meta.get("heads", 6)
    net = LeaguePolicy(n_catalogue + 2, len(unit_names) + 2, d=d, layers=layers, heads=heads, obs_v=obs_v)
    own = net.state_dict()
    for k, v in sd.items():
        if k in own and own[k].shape == v.shape:
            own[k] = v.clone()
    # Card tokens: catalogue order is append-only, so the old rows are a prefix.
    own["card_emb.weight"][: sd["card_emb.weight"].shape[0]] = sd["card_emb.weight"]
    # Unit tokens by name. Names the parent never had start at the mean.
    old = meta["units"]
    emb = sd["unit_emb.weight"]
    mean = emb[2:].mean(0)
    for i, name in enumerate(unit_names):
        j = old.get(name)
        own["unit_emb.weight"][i + 2] = emb[j] if j is not None else mean
    own["unit_emb.weight"][1] = emb[1]
    # unit_in: the parent's 7 columns; velocity starts at zero weight.
    w = torch.zeros_like(own["unit_in.weight"])
    w[:, :7] = sd["unit_in.weight"]
    own["unit_in.weight"] = w
    own["unit_in.bias"] = sd["unit_in.bias"].clone()
    te = own["type_emb.weight"]
    te[:6] = sd["type_emb.weight"]
    te[6:] = 0
    if obs_v >= 2:
        w = torch.zeros_like(own["state_in.weight"])
        w[:, :10] = sd["state_in.weight"]           # opponent elixir starts at zero weight
        own["state_in.weight"] = w
        own["state_in.bias"] = sd["state_in.bias"].clone()
    own["abil_in.weight"].zero_()
    own["abil_in.bias"].zero_()
    own["button_head.weight"].zero_()
    own["button_head.bias"].fill_(-6.0)
    own["wait_head.bias"] = sd["wait_head.bias"] + math.log(1 / wait_keep)
    net.load_state_dict(own)
    net.parent_meta = dict(path=str(path), wait_keep=wait_keep)
    return net


def split_logq(gate, mask, decide, time_temp, card_temp):
    """Split decoding (daybreak-cr style, 2026-11-23): play-or-wait at time_temp (as
    trained: an imitation model sharpened to 0.1 overall never plays), the card or button
    among the allowed ones at card_temp. Used by the actor in training (--train-card-temp)
    and by the learner (--card-temp) so PPO scores the policy the actors sampled."""
    g0 = gate.float()
    lw = gate_logq(g0 / time_temp, mask, decide)[:, :1]
    l_act = torch.log1p(-lw.exp().clamp(max=1 - 1e-6))
    la = torch.log_softmax((g0[:, 1:] / card_temp).masked_fill(~mask[:, 1:], -1e9), 1)
    return torch.cat([lw, la + l_act], 1).masked_fill(~mask, -1e9)
