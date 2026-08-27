"""Score the side classifier where the answer actually changes a decision.

Overall accuracy flatters any side rule, because most boxes are units sitting
on their owner's own half where position alone would have answered. The number
that matters is accuracy on units standing in **our** half: that is the set the
brain reads as a threat, and getting it wrong either invents a push that is not
there or hides one that is.

Reports the same breakdown as the colour-rule measurement it replaces, so the
two are directly comparable.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

YOLO = ROOT / "tmp" / "yolo"
from train_side_classifier import CROP, EXCLUDE, build_model  # noqa: E402

# Our half in normalised image coordinates. The dataset frames are full-arena
# captures, and the river sits at RIVER_Y of 32 rows.
RIVER = 16.0 / 32.0


def main() -> int:
    import torch

    names = {}
    for line in (YOLO / "cr.yaml").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(\d+):\s*(.+?)\s*$", line)
        if match:
            names[int(match.group(1))] = match.group(2)
    sides = json.loads((YOLO / "sides.json").read_text(encoding="utf-8"))

    blob = torch.load(YOLO / "side_classifier.pt", map_location="cpu",
                      weights_only=False)
    model = build_model()
    model.load_state_dict(blob["state_dict"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device).eval()

    label_dir, image_dir = YOLO / "labels" / "val", YOLO / "images" / "val"
    crops, truth, depth = [], [], []
    for stem in sorted(p.stem for p in label_dir.glob("*.txt")):
        frame_sides = sides.get(stem)
        if not frame_sides:
            continue
        path = next((image_dir / f"{stem}{ext}" for ext in (".jpg", ".png")
                     if (image_dir / f"{stem}{ext}").exists()), None)
        if path is None:
            continue
        pixels = np.asarray(Image.open(path).convert("RGB"))
        height, width = pixels.shape[:2]
        for index, line in enumerate((label_dir / f"{stem}.txt").read_text().split("\n")):
            parts = line.split()
            if len(parts) != 5 or index >= len(frame_sides):
                continue
            side = frame_sides[index]
            if side not in (0, 1) or names.get(int(parts[0]), "") in EXCLUDE:
                continue
            cx, cy, bw, bh = (float(v) for v in parts[1:])
            bw, bh = bw * 1.25, bh * 1.25
            x1, y1 = max(0, int((cx - bw / 2) * width)), max(0, int((cy - bh / 2) * height))
            x2 = min(width, int((cx + bw / 2) * width))
            y2 = min(height, int((cy + bh / 2) * height))
            if x2 - x1 < 6 or y2 - y1 < 6:
                continue
            crops.append(np.asarray(Image.fromarray(pixels[y1:y2, x1:x2])
                                    .resize((CROP, CROP), Image.BILINEAR)))
            truth.append(int(side))
            depth.append(cy)

    batch = torch.from_numpy(np.stack(crops).astype(np.float32) / 255.0)
    batch = batch.permute(0, 3, 1, 2)
    predicted, confidence = [], []
    with torch.no_grad():
        for start in range(0, len(batch), 2048):
            probabilities = torch.softmax(model(batch[start:start + 2048].to(device)), 1)
            best, index = probabilities.max(1)
            predicted.append(index.cpu())
            confidence.append(best.cpu())
    predicted = torch.cat(predicted).numpy()
    confidence = torch.cat(confidence).numpy()
    truth = np.array(truth)
    depth = np.array(depth)

    def report(label: str, mask: np.ndarray) -> None:
        if not mask.any():
            return
        accuracy = float((predicted[mask] == truth[mask]).mean())
        print(f"  {label:<34s} {100 * accuracy:5.1f}%   (n={int(mask.sum())})")

    print(f"val boxes: {len(truth)}\n")
    print("side classifier accuracy:")
    report("overall", np.ones(len(truth), bool))
    report("units in OUR half", depth > RIVER)
    report("units in THEIR half", depth <= RIVER)
    report("confident calls only (>=0.55)", confidence >= 0.55)
    covered = confidence >= 0.55
    print(f"\n  abstention rate at 0.55: "
          f"{100 * (1 - covered.mean()):.1f}% fall back to position")
    print("\nfor comparison, the colour rule this replaces:")
    print("  overall                             66.7%")
    print("  units in OUR half                   52.8%   (a coin flip)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
