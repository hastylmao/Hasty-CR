"""Train a Clash Royale unit detector on the published dataset.

Why one model with 201 classes rather than one per card: YOLO is multi-class by
construction, and the confusions are the point - a per-class model never sees a
Wizard, so it cannot learn that a Musketeer is not one. The existing detector
mislabelling spell particles as Bats is what that failure looks like.

One refinement worth knowing, from the author of this dataset: with ~150 classes
he ended up using **two** detectors split by object *scale*, because a Skeleton
is perhaps 20px and a King Tower 200px and a single anchor set struggles across
that range. This trains a single model first, to get a measured baseline before
adding that complexity.

Frames are 568x896, which is small, so this is an overnight job rather than a
week: roughly 3 hours for the `n` model and 6 for `s` at 640px on a 4070 Ti
SUPER. mAP starts being meaningful around epoch 10, so a run that is going
nowhere is obvious quickly.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tmp" / "yolo" / "cr.yaml"
RUNS = ROOT / "tmp" / "yolo" / "runs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the CR unit detector")
    parser.add_argument("--model", default="yolov8s.pt",
                        help="starting weights; yolov8n.pt is ~2x faster")
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--name", default="cr_detector")
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    from ultralytics import YOLO

    if not DATA.exists():
        print(f"missing {DATA}; run scripts/prepare_yolo_dataset.py first")
        return 1

    model = YOLO(args.model)
    model.train(
        data=str(DATA),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=0,
        workers=args.workers,
        project=str(RUNS),
        name=args.name,
        exist_ok=True,
        resume=args.resume,
        patience=args.patience,
        # Left on: these frames are all the same camera and scale, so the
        # geometric augmentations that help general detection matter less here
        # than colour, which varies with arena and with the red/blue side tint.
        hsv_h=0.015, hsv_s=0.7, hsv_v=0.4,
        degrees=0.0, shear=0.0, perspective=0.0,
        # A unit near our tower is never mirrored into the enemy half in this
        # game, but left-right is genuinely symmetric, so keep flips horizontal
        # only and never vertical.
        flipud=0.0, fliplr=0.5,
        mosaic=1.0, close_mosaic=10,
        # Images stay on disk: 5551 frames decoded would not fit comfortably in
        # RAM alongside the emulator and the model.
        cache=False,
        plots=True,
        val=True,
    )
    print(f"\nweights and curves under {RUNS / args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
