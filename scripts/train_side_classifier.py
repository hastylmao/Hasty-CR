"""Learn whose unit it is, since the detector only learns what it is.

The unit detector was trained on 201 classes with the dataset's side column
dropped, to keep the first run at 201 classes rather than 402. So it reports
"musketeer" but not whose musketeer, and the brain needs that for every single
decision it makes.

Guessing it does not work. Measured against the dataset's own side flags over
3,150 val boxes:

    more blue pixels than red            66.7%
    mean blueness > mean redness         64.0%
    position only: above screen middle   66.6%
    ...restricted to units in OUR half:
    colour rule                          52.8%     <- a coin flip
    position rule                        59.0%

Team tinting is far weaker a cue than it looks, and position is worthless in
the one situation that matters: a unit in our half is usually theirs, right up
until it is ours, which is precisely when the answer changes the play.

So this trains a small dedicated classifier on unit crops. A specialist is the
cheap option here - it reuses the 0.959 mAP detector untouched, trains on
~93k crops of a 2-class problem rather than re-fitting 402 classes on 5.5k
frames, and runs in well under a millisecond on the handful of boxes per frame.
The cue it can learn that colour cannot is orientation: troops walk toward the
enemy tower, so ally sprites face up the screen and enemy sprites face down.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
YOLO = ROOT / "tmp" / "yolo"
OUT = YOLO / "side_classifier.pt"
CROP = 32

# Static scenery and UI carry no team identity worth learning, and towers would
# flatter the score because they never move off their own half.
EXCLUDE = {
    "king-tower", "queen-tower", "tower-bar", "king-tower-bar", "cannoneer-tower",
    "bar", "text", "dirt", "clock", "emote", "elixir", "blood", "ruins",
    "background", "skeleton-king-bar",
}


def class_names() -> dict:
    names = {}
    for line in (YOLO / "cr.yaml").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(\d+):\s*(.+?)\s*$", line)
        if match:
            names[int(match.group(1))] = match.group(2)
    return names


def build_split(split: str, names: dict, sides: dict,
                limit: int | None = None) -> Tuple[np.ndarray, np.ndarray]:
    """Crop every labelled unit box and pair it with its ground-truth side."""
    label_dir, image_dir = YOLO / "labels" / split, YOLO / "images" / split
    stems = sorted(p.stem for p in label_dir.glob("*.txt"))
    if limit:
        random.Random(0).shuffle(stems)
        stems = stems[:limit]

    crops: List[np.ndarray] = []
    labels: List[int] = []
    for stem in stems:
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
            # Pad the box: the team-coloured element often sits just outside a
            # tight sprite box, and orientation reads better with context.
            bw, bh = bw * 1.25, bh * 1.25
            x1, x2 = int((cx - bw / 2) * width), int((cx + bw / 2) * width)
            y1, y2 = int((cy - bh / 2) * height), int((cy + bh / 2) * height)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)
            if x2 - x1 < 6 or y2 - y1 < 6:
                continue
            crop = Image.fromarray(pixels[y1:y2, x1:x2]).resize((CROP, CROP),
                                                                Image.BILINEAR)
            crops.append(np.asarray(crop))
            labels.append(int(side))
    return np.stack(crops), np.array(labels, dtype=np.int64)


def build_model():
    import torch.nn as nn

    def block(cin, cout):
        return nn.Sequential(
            nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(),
            nn.Conv2d(cout, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(),
            nn.MaxPool2d(2),
        )

    # Deliberately small: this runs on every detected box, every frame, next to
    # a YOLO pass and an emulator. ~300k parameters is enough for a two-class
    # problem with 90k examples.
    return nn.Sequential(
        block(3, 32), block(32, 64), block(64, 128),
        nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.1), nn.Linear(128, 2),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the ally/enemy classifier")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch", type=int, default=512)
    parser.add_argument("--lr", type=float, default=3e-3)
    parser.add_argument("--limit", type=int, help="use only N frames per split")
    args = parser.parse_args()

    import torch
    import torch.nn as nn

    names = class_names()
    sides = json.loads((YOLO / "sides.json").read_text(encoding="utf-8"))

    started = time.time()
    train_x, train_y = build_split("train", names, sides, args.limit)
    val_x, val_y = build_split("val", names, sides, args.limit)
    print(f"crops: train {len(train_x)}  val {len(val_x)}  "
          f"({time.time() - started:.0f}s to extract)")
    print(f"train balance: ally {int((train_y == 0).sum())}  "
          f"enemy {int((train_y == 1).sum())}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = build_model().to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.OneCycleLR(
        optimiser, max_lr=args.lr, total_steps=args.epochs *
        max(1, len(train_x) // args.batch + 1))
    # The split is ~60/40 enemy/ally because the recording player defends more
    # than they attack; weight the loss so the model cannot coast on the prior.
    weight = torch.tensor([len(train_y) / max(1, (train_y == 0).sum()),
                           len(train_y) / max(1, (train_y == 1).sum())],
                          dtype=torch.float32, device=device)
    weight = weight / weight.sum() * 2
    criterion = nn.CrossEntropyLoss(weight=weight)

    tx = torch.from_numpy(train_x).permute(0, 3, 1, 2).float().div_(255)
    ty = torch.from_numpy(train_y)
    vx = torch.from_numpy(val_x).permute(0, 3, 1, 2).float().div_(255).to(device)
    vy = torch.from_numpy(val_y).to(device)

    best = 0.0
    for epoch in range(args.epochs):
        model.train()
        order = torch.randperm(len(tx))
        total = 0.0
        for start in range(0, len(tx), args.batch):
            index = order[start:start + args.batch]
            xb = tx[index].to(device, non_blocking=True)
            yb = ty[index].to(device, non_blocking=True)
            # Horizontal flip only. Vertical would destroy the orientation cue
            # this model exists to learn.
            if random.random() < 0.5:
                xb = torch.flip(xb, dims=[3])
            optimiser.zero_grad(set_to_none=True)
            loss = criterion(model(xb), yb)
            loss.backward()
            optimiser.step()
            schedule.step()
            total += float(loss) * len(index)

        model.eval()
        with torch.no_grad():
            predicted = torch.cat([model(vx[i:i + 2048]).argmax(1)
                                   for i in range(0, len(vx), 2048)])
            accuracy = float((predicted == vy).float().mean())
            ally = float((predicted[vy == 0] == 0).float().mean())
            enemy = float((predicted[vy == 1] == 1).float().mean())
        print(f"epoch {epoch + 1:2d}/{args.epochs}  loss {total / len(tx):.4f}  "
              f"val {accuracy * 100:5.2f}%  (ally {ally * 100:5.1f}%  "
              f"enemy {enemy * 100:5.1f}%)")
        if accuracy > best:
            best = accuracy
            OUT.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"state_dict": model.state_dict(), "crop": CROP,
                        "accuracy": accuracy}, OUT)

    print(f"\nbest val accuracy {best * 100:.2f}%  ->  {OUT}")
    print("colour rule for comparison: 66.7% overall, 52.8% on units in our half")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
