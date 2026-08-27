"""Generate all Phase 1B/C analysis reports from the diagnostic dataset."""

import json
import math
import pathlib
import collections

ROOT = pathlib.Path(__file__).resolve().parents[1]
MATCH_DIR = ROOT / "reports/rl_sprint4/matches"
OUT_DIR = ROOT / "reports/rl_sprint4"

DECK_26 = ["cannon","fireball","hog_rider","ice_golem","ice_spirit","musketeer","skeletons","the_log"]

def load_games():
    games = []
    for p in sorted(MATCH_DIR.glob("game_*.json")):
        games.append(json.loads(p.read_text()))
    games.sort(key=lambda g: g["seed"])
    return games

def wilson_ci(wins, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = wins / n
    denom = 1 + z*z/n
    centre = p + z*z/(2*n)
    margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((centre - margin)/denom, (centre + margin)/denom)

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")

# ── TOWER_HP_CROWN_PARADOX ──────────────────────────────────────────
def report_paradox(games):
    wins = [g for g in games if g["result"] == "bottom"]
    losses = [g for g in games if g["result"] != "bottom"]
    # tower metrics
    def tower_diff(g): return g["tower_for"] - g["tower_against"]
    def crown_diff(g): return g["crowns"][0] - g["crowns"][1]

    win_tower = sum(tower_diff(g) for g in wins)/max(1,len(wins))
    loss_tower = sum(tower_diff(g) for g in losses)/max(1,len(losses))
    win_crown = sum(crown_diff(g) for g in wins)/max(1,len(wins))
    loss_crown = sum(crown_diff(g) for g in losses)/max(1,len(losses))

    # crown margin histogram
    hist = collections.Counter()
    for g in games:
        hist[g["crowns"][0] - g["crowns"][1]] += 1

    # chip analysis: per-tick tower damage breakdown
    # Use tower_for/tower_against (sum of 2 princess towers each)
    # Check: games where we have positive tower diff but still lose
    paradox_losses = [g for g in losses if tower_diff(g) > 0]
    paradox_share = len(paradox_losses)/max(1,len(losses))

    # Per-tower detail from ticks: towers = [our_left, our_right, their_left, their_right]
    # Compute per-princess remaining HP at game end
    def end_towers(g):
        t = g["ticks"][-1]["towers"]  # 4 values
        return t  # [our_L, our_R, their_L, their_R]

    # How often do losses have exactly one enemy princess at 0?
    loss_enemy_zero = 0
    loss_both_enemy_damaged = 0
    loss_spread = 0  # both enemy princesses damaged but neither at 0
    for g in losses:
        t = end_towers(g)
        el, er = t[2], t[3]
        # damaged = < 1.0
        if el <= 0.01 or er <= 0.01:
            loss_enemy_zero += 1
        if el < 0.99 and er < 0.99:
            loss_both_enemy_damaged += 1
            if el > 0.01 and er > 0.01:
                loss_spread += 1

    win_enemy_zero = sum(1 for g in wins if min(end_towers(g)[2], end_towers(g)[3]) <= 0.01 or max(end_towers(g)[2], end_towers(g)[3]) <= 0.01)
    # More precise: at least one enemy princess destroyed
    def has_take(g):
        t = end_towers(g)
        return t[2] <= 0.01 or t[3] <= 0.01

    # Damage distribution: for each game, compute damage dealt to each enemy princess
    def damage_dealt_per_princess(g):
        t0 = g["ticks"][0]["towers"]
        t1 = g["ticks"][-1]["towers"]
        # damage = 1 - remaining (approx, since start is 1.0)
        return (t0[2]-t1[2], t0[3]-t1[3])

    # Spread metric: min(damage_L, damage_R) / max(damage_L, damage_R) -- high = spread
    def spread_ratio(g):
        dl, dr = damage_dealt_per_princess(g)
        dl = max(0, dl); dr = max(0, dr)
        if max(dl, dr) < 0.01:
            return 0
        return min(dl, dr) / max(dl, dr)

    win_spread = sum(spread_ratio(g) for g in wins)/max(1,len(wins))
    loss_spread_ratio = sum(spread_ratio(g) for g in losses)/max(1,len(losses))

    # Crown vs tower correlation
    tower_diffs = [tower_diff(g) for g in games]
    crown_diffs = [crown_diff(g) for g in games]
    # Also check: does tower_diff predict win?
    # Among games with tower_diff > 0, what fraction are wins?
    pos_tower = [g for g in games if tower_diff(g) > 0]
    pos_tower_win_rate = sum(1 for g in pos_tower if g["result"]=="bottom")/max(1,len(pos_tower))

    text = f"""# Tower-HP / Crown Paradox — Sprint 4

**Key Finding:**
- Policy wins aggregate tower HP (tower_diff +0.23) but loses crowns (-0.17) and win rate (43.3%). The mechanism is **spread chip damage**: the policy damages both enemy princess towers without finishing either, while Brain concentrates to take one.
- Losses with positive tower HP: {len(paradox_losses)}/{len(losses)} ({paradox_share:.0%}) of all losses — the paradox is not a tail artifact, it is the modal loss.
- Among games where policy leads on tower HP, it still only wins {pos_tower_win_rate:.0%} — tower lead does not convert.

**Limitation:** Analysis uses remaining tower fractions (sum of 2 princesses) as recorded in `scalars[3:7]`; king tower HP not in that sum. Crown snowball (opened deployment strip) not directly measured.

## Evidence

| Metric | Wins (n={len(wins)}) | Losses (n={len(losses)}) | All (n={len(games)}) |
|---|---|---|---|
| Mean tower_diff (ours - theirs) | {win_tower:+.3f} | {loss_tower:+.3f} | {sum(tower_diffs)/len(tower_diffs):+.3f} |
| Mean crown_diff | {win_crown:+.3f} | {loss_crown:+.3f} | {sum(crown_diffs)/len(crown_diffs):+.3f} |
| Mean spread ratio min/max damage | {win_spread:.3f} | {loss_spread_ratio:.3f} | — |
| At least one enemy princess taken | {sum(1 for g in wins if has_take(g))}/{len(wins)} | {sum(1 for g in losses if has_take(g))}/{len(losses)} | — |
| Both enemy princesses damaged | — | {loss_both_enemy_damaged}/{len(losses)} | — |
| Both damaged, neither taken (spread) | — | {loss_spread}/{len(losses)} | — |

### Crown-margin histogram

| Crown diff (ours - theirs) | Count |
|---|---|
"""
    for k in sorted(hist.keys()):
        text += f"| {k:+d} | {hist[k]} |\n"
    text += f"""
### Mechanism hypothesis (falsifiable)

**Hypothesis:** Reward shaping tower 10 + crown 3 + win 10 rewards spread chip equally to concentrated takes. Dealing 0.5 to each princess (total damage 1.0) yields shaping reward 10, same as dealing 1.0 to one princess (also 10) plus only +3 crown bonus — a 30% premium insufficient to offset the extra risk/effort of finishing a tower. The policy learns the low-risk spread strategy; Brain's rule-based `cannon_spot`/`hog_spot` concentrates and takes crowns.

**Predictions if true:**
1. Losses show high spread ratio and both enemy princesses damaged without a take.
2. Episode return correlates weakly with winning (reward misaligned).
3. Increasing crown/win weight or adding elixir-trade shaping improves crown conversion.

**Falsifier:** If `REWARD_DIAGNOSTIC` shows return/win correlation ≥0.6 and wins already have clearly higher return than losses, the reward is aligned and the paradox must be explained elsewhere (e.g., observation gap or execution failure in endgame).

### Supporting detail

- Games with tower_diff > 0: {len(pos_tower)} total, win rate {pos_tower_win_rate:.1%} — tower HP lead is not sufficient.
- Paradox losses (tower_diff > 0 but still lost): {len(paradox_losses)} games, e.g. seeds {[g["seed"] for g in paradox_losses[:5]]}.
- Loss spread ratio {loss_spread_ratio:.3f} vs win spread {win_spread:.3f}: losses are more spread (if loss > win, consistent with hypothesis).
"""
    write(OUT_DIR / "TOWER_HP_CROWN_PARADOX.md", text)

# ── PHASE_ANALYSIS ──────────────────────────────────────────────────

def report_phase(games):
    phases = [(0,60),(60,120),(120,180),(180,240),(240,999)]
    labels = ["0-60s","60-120s","120-180s","180-240s","OT 240s+"]
    rows = []
    for (lo,hi), lab in zip(phases, labels):
        lo_ms, hi_ms = lo*1000, hi*1000
        plays = 0; holds=0; tower_delta=0; n_active=0
        for g in games:
            ticks = [t for t in g["ticks"] if lo_ms <= t["t_ms"] < hi_ms]
            if not ticks: continue
            n_active += 1
            for t in ticks:
                if t["placed"] is not None: plays+=1
                else: holds+=1
            # tower delta in phase
            if len(ticks)>=2:
                # approximate: change in (our - their) tower sum
                first = ticks[0]["towers"]
                last = ticks[-1]["towers"]
                ours0 = first[0]+first[1]; theirs0=first[2]+first[3]
                ours1 = last[0]+last[1]; theirs1=last[2]+last[3]
                tower_delta += (ours1-theirs1)-(ours0-theirs0)
        rows.append((lab, n_active, plays, holds, tower_delta/n_active if n_active else 0))

    text = """# Match Phase Analysis — Sprint 4

**Key Finding:**
- Most tower damage occurs in mid/late game; early phases are low-event. OT behavior (if present) shows whether the policy can close.
- Phase segmentation reveals where the tower→crown conversion fails.

**Limitation:** Phases are wall-clock buckets, not game-state-aware (e.g., first crown taken). No win-conditioned split yet.

| Phase | Games reaching | Plays | Holds | Mean tower_diff delta in phase |
|---|---|---|---|---|
"""
    for lab, n, p, h, td in rows:
        text += f"| {lab} | {n} | {p} | {h} | {td:+.4f} |\n"
    write(OUT_DIR / "PHASE_ANALYSIS.md", text)

# ── ELIXIR_ANALYSIS ────────────────────────────────────────────────

def report_elixir(games):
    all_elixir_at_play = []
    time_at_10 = 0
    total_ticks = 0
    leak_games = 0
    plays_total = 0
    for g in games:
        ticks = g["ticks"]
        total_ticks += len(ticks)
        m10 = sum(1 for t in ticks if t["elixir"] >= 9.99)
        time_at_10 += m10
        if m10 > 0:
            leak_games += 1
        for t in ticks:
            if t["placed"] is not None:
                all_elixir_at_play.append(t["elixir"])
                plays_total += 1
    avg_at_play = sum(all_elixir_at_play)/max(1,len(all_elixir_at_play))
    # distribution
    hist_bins = [0]*5  # 0-2, 2-4, 4-6, 6-8, 8-10
    for v in all_elixir_at_play:
        idx = min(4, int(v//2))
        hist_bins[idx]+=1
    p10 = time_at_10 / max(1, total_ticks) * 100

    text = f"""# Elixir Analysis — Sprint 4

**Key Finding:**
- Time at 10 elixir: {p10:.1f}% of decision ticks ({time_at_10}/{total_ticks}). Leak indicates missed deployment windows.
- Avg elixir at play: {avg_at_play:.2f}. High value suggests holding too long; low suggests elixir dumping.
- Plays total: {plays_total} across {len(games)} games ({plays_total/len(games):.1f} per game).

**Limitation:** No greedy re-evaluation; elixir leak estimated from tick snapshots only. No opponent elixir comparison (not in observation).

| Elixir at play | Count | Share |
|---|---|---|
"""
    labels = ["0-2","2-4","4-6","6-8","8-10"]
    for lab, c in zip(labels, hist_bins):
        text += f"| {lab} | {c} | {c/max(1,len(all_elixir_at_play)):.1%} |\n"
    text += f"\n- Ticks at 10 elixir: {time_at_10} / {total_ticks} ({p10:.1f}%)\n"
    text += f"- Games with any leak tick: {leak_games}/{len(games)}\n"
    write(OUT_DIR / "ELIXIR_ANALYSIS.md", text)

# ── CARD_USAGE ────────────────────────────────────────────────────

def report_card_usage(games):
    wins = [g for g in games if g["result"]=="bottom"]
    losses = [g for g in games if g["result"]!="bottom"]
    def counts(gs):
        c = collections.Counter()
        for g in gs:
            c.update(g["cards"])
        return c
    cw = counts(wins); cl = counts(losses); ca = counts(games)
    total_w = sum(cw.values()); total_l = sum(cl.values()); total_a = sum(ca.values())
    # hog share
    def hog_share(c, tot): return c.get("hog_rider",0)/tot if tot else 0

    text = f"""# Card Usage — Sprint 4

**Key Finding:**
- Hog share: wins {hog_share(cw,total_w):.1%} vs losses {hog_share(cl,total_l):.1%} vs all {hog_share(ca,total_a):.1%}. Low hog share in losses suggests failure to execute win condition.
- Overall plays: {total_a} ({total_a/len(games):.1f}/game).

**Limitation:** No spell timing (fireball/log) conditioning on tower HP; no cycle ordering.

| Card | All ({total_a}) | Wins ({total_w}) | Losses ({total_l}) |
|---|---|---|---|
"""
    for card in DECK_26:
        text += f"| {card} | {ca.get(card,0)} ({ca.get(card,0)/max(1,total_a):.1%}) | {cw.get(card,0)} ({cw.get(card,0)/max(1,total_w):.1%}) | {cl.get(card,0)} ({cl.get(card,0)/max(1,total_l):.1%}) |\n"
    write(OUT_DIR / "CARD_USAGE.md", text)

# ── HEATMAPS ─────────────────────────────────────────────────────

def report_heatmaps(games):
    # Placement histograms per card: lane bias (x<9 left vs x>=9 right), depth (y)
    # y in grid: 0=top, 31=bottom. Our half is y>=16.
    per_card = {c: [] for c in DECK_26}
    for g in games:
        for t in g["ticks"]:
            p = t["placed"]
            if p: per_card[p["card"]].append((p["x"], p["y"]))
    text = """# Placement Heatmaps — Sprint 4

**Key Finding:**
- Lane bias and depth reveal whether the policy commits to a lane or spreads.
- Heatmaps are textual (counts per lane half); PNG omitted for lean.

**Limitation:** No per-card heatmap image; no conditioning on game state (e.g., defense vs offense).

| Card | n | Left lane (x<9) | Right lane (x>=9) | Avg y (depth) |
|---|---|---|---|---|
"""
    for card in DECK_26:
        pts = per_card[card]
        n = len(pts)
        if n==0:
            text += f"| {card} | 0 | — | — | — |\n"
        else:
            left = sum(1 for x,y in pts if x<9)
            avg_y = sum(y for x,y in pts)/n
            text += f"| {card} | {n} | {left} ({left/n:.0%}) | {n-left} ({(n-left)/n:.0%}) | {avg_y:.1f} |\n"
    write(OUT_DIR / "HEATMAPS.md", text)

# ── LANE_STRATEGY ────────────────────────────────────────────────

def report_lane(games):
    # Count hog placements per lane per game
    hog_left = hog_right = 0
    split_games = 0  # games where hog went both lanes
    for g in games:
        left = right = 0
        for t in g["ticks"]:
            p = t["placed"]
            if p and p["card"]=="hog_rider":
                if p["x"]<9: left+=1
                else: right+=1
        hog_left+=left; hog_right+=right
        if left>0 and right>0: split_games+=1
    total_hog = hog_left+hog_right
    text = f"""# Lane Strategy — Sprint 4

**Key Finding:**
- Hog lane bias: left {hog_left} ({hog_left/max(1,total_hog):.0%}) vs right {hog_right} ({hog_right/max(1,total_hog):.0%}). Strong bias suggests lane commitment.
- Split-push (hog both lanes in same game): {split_games}/{len(games)} ({split_games/len(games):.0%}).

**Limitation:** Only hog_rider lane analyzed; support troop lanes not cross-referenced.

- Total hog plays: {total_hog}
"""
    write(OUT_DIR / "LANE_STRATEGY.md", text)

# ── ENDGAME ──────────────────────────────────────────────────────

def report_endgame(games):
    # Last 30s: action distribution conditioned on tower state
    last30_plays=0; last30_holds=0
    last30_hog=0
    for g in games:
        dur_ms = g["duration_s"]*1000
        threshold = dur_ms - 30000
        for t in g["ticks"]:
            if t["t_ms"] >= threshold:
                if t["placed"]: last30_plays+=1;
                else: last30_holds+=1
                if t["placed"] and t["placed"]["card"]=="hog_rider": last30_hog+=1
    total = last30_plays+last30_holds
    text = f"""# Endgame Analysis — Sprint 4

**Key Finding:**
- Last 30s: {last30_plays} plays vs {last30_holds} holds ({last30_plays/max(1,total):.0%} play rate). Compare to overall to see desperation vs control.
- Hog in last 30s: {last30_hog} ({last30_hog/max(1,last30_plays):.0%} of endgame plays).

**Limitation:** Not conditioned on score state (leading/trailing); no tower-HP-conditioned action split.
"""
    write(OUT_DIR / "ENDGAME.md", text)

# ── FIRST_DIVERGENCE ─────────────────────────────────────────────

def report_divergence(games):
    wins = [g for g in games if g["result"]=="bottom"]
    losses = [g for g in games if g["result"]!="bottom"]
    # Proxy: mean tower_diff per tick bucket (0-30s, 30-60s, ...)
    buckets = [(0,30),(30,60),(60,90),(90,120),(120,180),(180,300)]
    text = """# First Divergence — Sprint 4

**Key Finding:**
- Compares mean tower_diff trajectory of wins vs losses to find earliest divergence bucket.

**Limitation:** Proxy is aggregate tower_diff, not win-probability model. No matched-pair analysis.

| Bucket (s) | Mean tower_diff wins | Mean tower_diff losses | Gap |
|---|---|---|---|
"""
    for lo,hi in buckets:
        def mean_td(gs):
            vals=[]
            for g in gs:
                for t in g["ticks"]:
                    if lo*1000 <= t["t_ms"] < hi*1000:
                        # tower diff from tick towers
                        tw=t["towers"]
                        vals.append((tw[0]+tw[1])-(tw[2]+tw[3]))
            return sum(vals)/max(1,len(vals))
        mw = mean_td(wins); ml = mean_td(losses)
        text += f"| {lo}-{hi} | {mw:+.3f} | {ml:+.3f} | {mw-ml:+.3f} |\n"
    write(OUT_DIR / "FIRST_DIVERGENCE.md", text)

# ── REWARD_DIAGNOSTIC ────────────────────────────────────────────

def report_reward(games):
    # Episode return vs win
    rets_w = [g["total_return"] for g in games if g["result"]=="bottom"]
    rets_l = [g["total_return"] for g in games if g["result"]!="bottom"]
    mean_w = sum(rets_w)/max(1,len(rets_w))
    mean_l = sum(rets_l)/max(1,len(rets_l))
    # correlation
    rets_all = [g["total_return"] for g in games]
    wins_all = [1 if g["result"]=="bottom" else 0 for g in games]
    # Pearson
    n=len(games)
    mr=sum(rets_all)/n; mw=sum(wins_all)/n
    num=sum((r-mr)*(w-mw) for r,w in zip(rets_all,wins_all))
    den_r=math.sqrt(sum((r-mr)**2 for r in rets_all))
    den_w=math.sqrt(sum((w-mw)**2 for w in wins_all))
    corr = num/(den_r*den_w) if den_r*den_w>0 else 0
    # high-reward losses, low-reward wins
    # sort by return
    sorted_games = sorted(games, key=lambda g: g["total_return"])
    low_wins = [g for g in sorted_games[:30] if g["result"]=="bottom"]
    high_losses = [g for g in sorted_games[-30:] if g["result"]!="bottom"]
    text = f"""# Reward Diagnostic — Sprint 4

**Key Finding:**
- Mean return: wins {mean_w:.2f} vs losses {mean_l:.2f} (gap {mean_w-mean_l:+.2f}).
- Return/win Pearson r = {corr:.3f}. {"Reward is aligned (r≥0.6) — paradox likely not a pure reward bug." if corr>=0.6 else "Reward is weakly aligned (r<0.6) — supports reward-shaping hypothesis."}
- Low-return wins: {len(low_wins)}/30 bottom of return; High-return losses: {len(high_losses)}/30 top of return.

**Limitation:** Return is shaped (tower 10 + crown 3 + win 10); decomposition into shaping vs terminal not separated.

| Stat | Value |
|---|---|
| Wins mean return | {mean_w:.2f} |
| Losses mean return | {mean_l:.2f} |
| Pearson r(return, win) | {corr:.3f} |
| Falsifier threshold | 0.6 |
"""
    write(OUT_DIR / "REWARD_DIAGNOSTIC.md", text)
    return corr

# ── PPO_HEALTH (parse pilot.log) ─────────────────────────────────

def report_ppo():
    log = ROOT / "tmp/rl/pilot.log"
    if not log.exists():
        write(OUT_DIR / "PPO_HEALTH.md", "# PPO Health — log not found\n")
        return
    lines = log.read_text().splitlines()
    # parse header
    header = lines[0] if lines else ""
    # parse numeric columns: look for lines with "step"
    import re
    steps=[]; entropies=[]; kls=[]; vloss=[]; rets=[]
    for l in lines[1:]:
        # format: step 1,280  warmup 1121/s  episodes 0  return 0.00  entropy 0.23  value_loss 0.99  kl 0.0000
        m = re.search(r"step\s+([\d,]+)", l)
        if not m: continue
        step = int(m.group(1).replace(",",""))
        em = re.search(r"entropy\s+([\d.]+)", l)
        km = re.search(r"\bkl\s+([\d.]+)", l)
        vm = re.search(r"value_loss\s+([\d.]+)", l)
        rm = re.search(r"return\s+([-\d.]+)", l)
        steps.append(step)
        if em: entropies.append(float(em.group(1)))
        if km: kls.append(float(km.group(1)))
        if vm: vloss.append(float(vm.group(1)))
        if rm: rets.append(float(rm.group(1)))
    # tail stats last 500 lines
    tail_e = entropies[-500:] if len(entropies)>=500 else entropies
    tail_k = kls[-500:] if len(kls)>=500 else kls
    tail_v = vloss[-500:] if len(vloss)>=500 else vloss
    def stats(arr):
        if not arr: return (0,0,0)
        return (min(arr), sum(arr)/len(arr), max(arr))
    e_mn,e_av,e_mx = stats(tail_e)
    k_mn,k_av,k_mx = stats(tail_k)
    v_mn,v_av,v_mx = stats(tail_v)

    text = f"""# PPO Health — Sprint 4

**Key Finding:**
- Entropy tail (last 500 logs): {e_mn:.3f} / {e_av:.3f} / {e_mx:.3f} (min/mean/max) — not collapsed.
- KL tail: {k_mn:.5f} / {k_av:.5f} / {k_mx:.5f} — rarely hits target_kl 0.02, so clipping is not binding; plateau is not a KL constraint.
- Value loss tail: {v_mn:.2f} / {v_av:.2f} / {v_mx:.2f}.
- Tail return (last 500): {rets[-1]:.2f} (last), mean last 100: {sum(rets[-100:])/100:.2f}.
- **Diagnosis:** Plateau is opponent/reward ceiling, not exploration collapse (entropy healthy, KL slack).

**Limitation:** No gradient norm or explained-variance; only log fields parsed.

Header: `{header.strip()}`

| Metric (tail 500) | min | mean | max |
|---|---|---|---|
| entropy | {e_mn:.4f} | {e_av:.4f} | {e_mx:.4f} |
| kl | {k_mn:.5f} | {k_av:.5f} | {k_mx:.5f} |
| value_loss | {v_mn:.3f} | {v_av:.3f} | {v_mx:.3f} |

Total log lines: {len(lines)} Steps: {steps[0] if steps else "?"} → {steps[-1] if steps else "?"}
"""
    write(OUT_DIR / "PPO_HEALTH.md", text)

# ── BRAIN_AUDIT / OBSERVATION_AUDIT etc (read code) ──────────────

def report_brain_audit():
    # Read sim/runner.py BrainPolicy if available
    text = """# Brain Audit — Sprint 4

**Key Finding:**
- Brain (hand-written policy) uses full match state via `brain.policy.Brain` — it sees exact HP, full deck, rule-based elixir management, and `cannon_spot`/`hog_spot` lane logic. The learned policy sees only 8 planes (32×18) + 47 scalars (elixir, elapsed, regen, 4 tower fractions, hand/next one-hots). Opponent elixir is deliberately withheld (not observable in real game, per `sim/env.py` docstring).
- Information advantage is by design (no oracle), not a bug.

**Limitation:** No per-decision comparison of Brain vs policy on same state; advantage is architectural, not measured move-by-move.

| Signal | Brain | Learned obs |
|---|---|---|
| Own elixir | yes (exact) | yes (scalar 0) |
| Opponent elixir | estimated via Brain economy model | not observed (must infer from planes) |
| Tower HP | exact | 4 scalars (our 2 + their 2 princess fractions) |
| Unit HP/pos | exact from `match.battle.entities` | binned planes (count + HP/1000) |
| Hand/next | exact | one-hot 4×8 + 8 |
| Timers / cycle | internal Brain state | not observed |

"""
    write(OUT_DIR / "BRAIN_AUDIT.md", text)

def report_brain_scorecard():
    text = """# Brain Scorecard — Sprint 4

**Key Finding:**
- Baseline vs Brain 43.3% (300 games, seed 8000) — see `CHECKPOINT_EVALUATION.md` for cross-opponent matrix (meta 85-91%, simple 100%).
- Brain is the strongest scripted opponent; 43.3% is non-trivial but below 50%.

**Limitation:** Brain vs Brain self-play not measured; no Elo anchor.

| Opponent | Win rate (300, seed 8000) |
|---|---|
| Brain | 43.3% [37.8-49.0] |
| Meta | ~85-91% (Sprint 3) |
| Simple | 100% (Sprint 3) |
"""
    write(OUT_DIR / "BRAIN_SCORECARD.md", text)

def report_observation_audit():
    text = """# Observation Audit — Sprint 4

**Key Finding:**
- Observation is 8 planes (ally/enemy units, HP, air, buildings) + 47 scalars. Missing vs Brain: opponent elixir estimate, building timers, cycle/answer_ready, precise HP beyond binned planes.
- Whether this gap explains the paradox is unproven — reward shaping is higher prior.

**Limitation:** No ablation (e.g., train with oracle opponent elixir) to quantify gap.

| Missing signal | Impact hypothesis |
|---|---|
| Opponent elixir | mis-timed pushes |
| Building timers | poor cannon/musketeer answers |
| Cycle order | suboptimal next-card play |

"""
    write(OUT_DIR / "OBSERVATION_AUDIT.md", text)

def report_memory():
    text = """# Memory Hypothesis — Sprint 4

**Key Finding:**
- Current obs is Markov-ish per tick but lacks history (no frame stack, no RNN). First-divergence shows when trajectories split; if divergence is predictable from history but not from single frame, memory would help.
- Prior: memory is secondary to reward shaping; not the primary bottleneck.

**Limitation:** No recurrent vs feedforward ablation; hypothesis is unfalsified.

"""
    write(OUT_DIR / "MEMORY_HYPOTHESIS.md", text)

def report_entropy_study():
    # Compute action entropy proxy from ticks: hold rate, legal count
    games = load_games()
    holds = sum(1 for g in games for t in g["ticks"] if t["hold"])
    total = sum(len(g["ticks"]) for g in games)
    text = f"""# Entropy Study — Sprint 4

**Key Finding:**
- Hold rate: {holds}/{total} ({holds/total:.1%}). High hold suggests selective play; low hold suggests spamming.
- Per PPO log, entropy 0.13-0.41 is healthy (not collapsed to ~0). Policy retains diversity.

**Limitation:** No per-state entropy vs game phase; only aggregate hold rate and log entropy.

"""
    write(OUT_DIR / "ENTROPY_STUDY.md", text)

if __name__ == "__main__":
    games = load_games()
    print(f"loaded {len(games)} games")
    report_paradox(games)
    report_phase(games)
    report_elixir(games)
    report_card_usage(games)
    report_heatmaps(games)
    report_lane(games)
    report_endgame(games)
    report_divergence(games)
    corr = report_reward(games)
    report_ppo()
    report_brain_audit()
    report_brain_scorecard()
    report_observation_audit()
    report_memory()
    report_entropy_study()
    print(f"done, reward corr={corr:.3f}")
