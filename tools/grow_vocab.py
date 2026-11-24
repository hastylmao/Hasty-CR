"""Re-key an imitation checkpoint to a newer rows vocabulary, so it can be the
--init of sim.train_tokens on rows built by a later engine.

    .venvs/buildabot/Scripts/python.exe tools/grow_vocab.py runs/tokens/rs_big/best.pt data/rs_rows_golem runs/tokens/rs_big/best_v147.pt

Card tokens are catalogue index + 2 and the catalogue is append-only, so old
rows are a prefix. Unit tokens are matched by name (meta "units"); names the
old model never had start at the mean of its unit embeddings.
"""
import json
import sys
from pathlib import Path

import torch

src, data, dst = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
blob = torch.load(src, map_location="cpu", weights_only=False)
sd, meta = blob["model"], blob["meta"]
new = json.loads((data / "vocab.json").read_text())
ce = sd["card_emb.weight"]
grown = ce.new_zeros(new["n_cards"], ce.shape[1])
grown[: ce.shape[0]] = ce
grown[ce.shape[0]:] = ce[2:].mean(0)
sd["card_emb.weight"] = grown
ue = sd["unit_emb.weight"]
mean = ue[2:].mean(0)
out = ue.new_zeros(new["n_units"], ue.shape[1])
out[:2] = ue[:2]
old = meta["units"]
hit = 0
for name, tok in new["units"].items():
    j = old.get(name)
    out[tok] = ue[j] if j is not None else mean
    hit += j is not None
sd["unit_emb.weight"] = out
blob["meta"] = dict(meta, **{k: new[k] for k in ("n_cards", "n_units", "cards", "units")})
torch.save(blob, dst)
print(f"cards {ce.shape[0]} -> {new['n_cards']}, units {ue.shape[0]} -> {new['n_units']} ({hit} by name)")
