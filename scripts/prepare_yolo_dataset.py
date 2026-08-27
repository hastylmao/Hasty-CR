"""Convert the published Clash Royale dataset into a standard YOLO layout.

Two mismatches have to be fixed, and both are silent failures if missed.

**Label width.** The dataset's label lines carry twelve columns:

    0 0.500000 0.130580 0.187374 0.153061 1 0 0 0 0 0 0
    ^ class    ^x       ^y       ^w       ^h ^side ^six unused

Ultralytics expects exactly five (`class x y w h`). Column six is the **side**
flag - 0 for the bottom player, 1 for the top - which is genuinely useful to the
bot later, since knowing ally from enemy is half of reading the board. It is
recorded in `sides.json` here rather than thrown away, but kept out of the class
index for now: folding it in would double 201 classes to 402 and make the first
training run harder than it needs to be.

**Directory layout.** The dataset keeps each label beside its image
(`00810.jpg` next to `00810.txt`). Ultralytics finds labels by swapping
`/images/` for `/labels/` in the path, so the upstream author patched
ultralytics itself to cope. Restructuring the data instead leaves the library
untouched, which is the cheaper thing to maintain.

Images are hard-linked, not copied, so the 640MB dataset is not duplicated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor" / "CR-Detection-Dataset" / "images" / "part2"
OUT = ROOT / "tmp" / "yolo"


def read_class_names(yaml_path: Path) -> Dict[int, str]:
    """Pull `id: name` out of the dataset's yaml without a yaml dependency."""
    names: Dict[int, str] = {}
    in_names = False
    for line in yaml_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("names:"):
            in_names = True
            continue
        if in_names:
            match = re.match(r"\s+(\d+):\s*(.+?)\s*$", line)
            if match:
                names[int(match.group(1))] = match.group(2)
            elif line.strip() and not line.startswith(" "):
                break
    return names


def flat_name(relative: str) -> str:
    """`./WTY_20240305/1/00810.jpg` -> `WTY_20240305_1_00810`.

    Flattened because every episode folder restarts numbering at 00000, so a
    flat directory would silently overwrite thousands of frames.
    """
    stem = relative.lstrip("./").rsplit(".", 1)[0]
    return stem.replace("/", "_").replace("\\", "_")


def convert_split(name: str, listing: Path, sides: Dict[str, List[int]]) -> Tuple[int, int]:
    image_dir = OUT / "images" / name
    label_dir = OUT / "labels" / name
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)

    frames = boxes = 0
    for line in listing.read_text(encoding="utf-8", errors="replace").splitlines():
        relative = line.strip().split()[0] if line.strip() else ""
        if not relative:
            continue
        source_image = (SOURCE / relative.lstrip("./")).resolve()
        source_label = source_image.with_suffix(".txt")
        if not source_image.exists() or not source_label.exists():
            continue

        stem = flat_name(relative)
        target_image = image_dir / f"{stem}{source_image.suffix}"
        if not target_image.exists():
            try:
                os.link(source_image, target_image)      # hard link, no copy
            except OSError:
                shutil.copyfile(source_image, target_image)

        rows, frame_sides = [], []
        for raw in source_label.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = raw.split()
            if len(parts) < 5:
                continue
            cls, x, y, w, h = parts[:5]
            # Guard against a stray out-of-range coordinate: ultralytics rejects
            # the whole label file rather than the offending line.
            try:
                values = [float(v) for v in (x, y, w, h)]
            except ValueError:
                continue
            if not all(0.0 <= v <= 1.0 for v in values):
                continue
            rows.append(f"{int(cls)} {x} {y} {w} {h}")
            frame_sides.append(int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else -1)
        (label_dir / f"{stem}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
        sides[stem] = frame_sides
        frames += 1
        boxes += len(rows)
    return frames, boxes


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the YOLO dataset")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    yaml_path = SOURCE / "ClashRoyale_detection.yaml"
    names = read_class_names(yaml_path)
    if not names:
        print("could not read class names from the dataset yaml")
        return 1

    sides: Dict[str, List[int]] = {}
    total = {}
    for split, listing in (("train", SOURCE / "train_annotation.txt"),
                           ("val", SOURCE / "val_annotation.txt")):
        if not listing.exists():
            print(f"missing {listing}")
            return 1
        frames, boxes = convert_split(split, listing, sides)
        total[split] = (frames, boxes)
        print(f"{split:5s} {frames:5d} frames  {boxes:6d} boxes")

    (args.out / "sides.json").write_text(json.dumps(sides), encoding="utf-8")

    highest = max(names)
    lines = [f"path: {args.out.resolve().as_posix()}",
             "train: images/train", "val: images/val", "names:"]
    lines += [f"  {index}: {names.get(index, f'class_{index}')}"
              for index in range(highest + 1)]
    (args.out / "cr.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n{len(names)} named classes, {highest + 1} slots -> {args.out / 'cr.yaml'}")
    print(f"side flags for {len(sides)} frames -> {args.out / 'sides.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
