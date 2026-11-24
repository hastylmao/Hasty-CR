"""Search-label rows -> training rows for engine_bc.py --tile-only (2026-11-13).

actor.py --search-labels writes every searched play with tile = the search's best
candidate. A best score that beats the policy's own tile by less than --margin is
noise (ties are common: a spell that hits nothing scores the same everywhere), so
those rows get the policy's tile back. Rows are re-chunked to 4,000 per file.

    python tools/league/search_distill_prep.py --src runs/league/search_labels1 --out runs/league/search_rows1

UNVERIFIED: margin 0.02 is daybreak-cr's value (their scores are on the same scale:
crowns + tower hp fractions + 0.3 x unit hp in princess towers), not measured here.
"""
import argparse
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--margin", type=float, default=0.02)
    a = ap.parse_args()
    files = sorted(f for s in a.src for f in (ROOT / s).glob("rows_*.npz"))
    parts = [dict(np.load(f)) for f in files]
    cat = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    n = len(cat["a"])
    best = np.nanmax(cat["score"], 1)
    gain = best - cat["score"][:, 0]            # candidate 0 is the policy's own tile
    gain = np.where(np.isnan(gain), np.inf, gain)   # the policy's tile failed in the copy: keep the search's
    moved = gain > a.margin
    cat["tile"] = np.where(moved, cat["tile"], cat["policy_tile"])
    order = np.random.default_rng(0).permutation(n)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    for k, s in enumerate(range(0, n, 4000)):
        idx = order[s:s + 4000]
        np.savez(out / f"rows_{k:05d}.npz", **{key: v[idx] for key, v in cat.items() if key not in ("cand", "score", "policy_tile")})
    g = gain[np.isfinite(gain)]
    print(f"{n:,} labels from {len(files)} files; moved by more than {a.margin}: {moved.mean():.3f}; "
          f"gain median {np.median(g):.3f} mean {g.mean():.3f} p90 {np.quantile(g, .9):.3f}")


if __name__ == "__main__":
    main()
