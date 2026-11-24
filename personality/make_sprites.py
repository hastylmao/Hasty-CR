"""Build transparent Sonny sprites from green-screen portraits.

    python -m personality.make_sprites --src <dir with sonny_*.jpg/png>

Generated portraits (green #00FF00 background) are keyed to alpha and saved as
`personality/assets/sonny_<emotion>.png` (512x512). Any emotion without its own
source image is derived from a base face with simple, deliberately cheap edits
(sweat drops, blush, a tear, red eyes) - drop a real generation named
`sonny_<emotion>.*` into --src and re-run to replace a derived one.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ASSETS = Path(__file__).resolve().parent / "assets"
EMOTIONS = ("neutral", "cocky", "panicking", "irritated", "delusional",
            "embarrassed", "vengeful", "defeated")
SIZE = 512


def chroma_key(img: Image.Image) -> Image.Image:
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # How much greener than the other channels: 0 = subject, high = screen.
    green = g - np.maximum(r, b)
    alpha = np.clip(1.0 - (green - 40) / 60.0, 0, 1)
    # Despill: pull residual green on the edges down to the other channels.
    g2 = np.where(green > 0, np.maximum(r, b) + np.minimum(green, 10), g)
    out = np.dstack([r, g2, b, alpha * 255]).astype(np.uint8)
    im = Image.fromarray(out, "RGBA")
    al = im.getchannel("A").filter(ImageFilter.GaussianBlur(0.8))
    im.putalpha(al)
    return im.resize((SIZE, SIZE), Image.LANCZOS)


# Face landmarks on the 512 base framing (eyes ~y185, cheeks ~y260).
EYES = ((193, 188), (316, 188))
CHEEKS = ((185, 270), (325, 270))


def _overlay(base: Image.Image, draw_fn) -> Image.Image:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    return Image.alpha_composite(base, layer)


def derive(kind: str, faces: dict) -> Image.Image:
    neutral = faces["neutral"]
    if kind == "panicking":
        im = ImageEnhance.Brightness(neutral).enhance(1.08)

        def d(dr):
            for (x, y, s) in ((150, 110, 1.0), (360, 95, 0.8), (385, 150, 0.6)):
                w, h = 22 * s, 34 * s
                dr.ellipse((x - w / 2, y, x + w / 2, y + h), fill=(150, 210, 255, 230),
                           outline=(60, 120, 200, 255), width=2)
                dr.polygon([(x - w / 2 + 2, y + h / 3), (x, y - h / 2), (x + w / 2 - 2, y + h / 3)],
                           fill=(150, 210, 255, 230))
            for (ex, ey) in EYES:   # pinprick pupils: white-out around the iris
                dr.ellipse((ex - 20, ey - 11, ex + 20, ey + 11), fill=(245, 245, 245, 235))
                dr.ellipse((ex - 3, ey - 3, ex + 3, ey + 3), fill=(10, 10, 10, 255))
        return _overlay(im, d)
    if kind == "embarrassed":
        src = faces.get("cocky", neutral)

        def d(dr):
            for (cx, cy) in CHEEKS:
                dr.ellipse((cx - 38, cy - 18, cx + 38, cy + 18), fill=(255, 90, 120, 110))
            for k in range(3):
                x = 175 + k * 22
                dr.line((x, 262, x + 10, 280), fill=(220, 60, 90, 200), width=3)
                dr.line((x + 140, 262, x + 150, 280), fill=(220, 60, 90, 200), width=3)
        blush = _overlay(src, d)
        return Image.alpha_composite(Image.new("RGBA", blush.size, (0, 0, 0, 0)),
                                     blush.filter(ImageFilter.GaussianBlur(0.3)))
    if kind == "vengeful":
        src = faces.get("irritated", neutral)
        im = ImageEnhance.Contrast(src).enhance(1.25)
        im = ImageEnhance.Brightness(im).enhance(0.85)

        def d(dr):
            for (ex, ey) in EYES:
                dr.ellipse((ex - 12, ey - 9, ex + 12, ey + 9), fill=(255, 20, 20, 170))
                dr.ellipse((ex - 4, ey - 4, ex + 4, ey + 4), fill=(255, 220, 220, 230))
        return _overlay(im, d)
    if kind == "defeated":
        g = ImageEnhance.Color(neutral).enhance(0.15)
        g = ImageEnhance.Brightness(g).enhance(0.8).rotate(-9, resample=Image.BICUBIC,
                                                         center=(256, 400))

        def d(dr):
            x, y = EYES[1][0] - 2, EYES[1][1] + 14
            dr.ellipse((x - 7, y, x + 7, y + 20), fill=(140, 200, 255, 220))
            dr.line((x, y + 20, x + 4, y + 70), fill=(140, 200, 255, 160), width=5)
        return _overlay(g, d)
    if kind == "delusional":
        src = faces.get("cocky", neutral)
        im = ImageEnhance.Color(src).enhance(1.6)
        im = ImageEnhance.Brightness(im).enhance(1.1)

        def d(dr):
            for (cx, cy, r) in ((110, 90, 18), (410, 70, 14), (430, 220, 10), (90, 230, 12)):
                dr.polygon([(cx, cy - r), (cx + r / 4, cy - r / 4), (cx + r, cy), (cx + r / 4, cy + r / 4),
                            (cx, cy + r), (cx - r / 4, cy + r / 4), (cx - r, cy), (cx - r / 4, cy - r / 4)],
                           fill=(255, 235, 120, 235))
            for (ex, ey) in EYES:          # spiral-ish glazed eyes
                dr.ellipse((ex - 9, ey - 7, ex + 9, ey + 7), outline=(255, 255, 255, 200), width=2)
        return _overlay(im, d)
    return neutral


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path)
    args = ap.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)
    faces = {}
    for emo in EMOTIONS:
        hits = sorted(args.src.glob(f"sonny_{emo}*.*"))
        hits = [h for h in hits if h.suffix.lower() in (".png", ".jpg", ".jpeg")]
        if hits:
            faces[emo] = chroma_key(Image.open(hits[-1]))
            print(f"keyed    {emo:12s} <- {hits[-1].name}")
    if "neutral" not in faces:
        raise SystemExit("need at least sonny_neutral.* in --src")
    for emo in EMOTIONS:
        if emo not in faces:
            faces[emo] = derive(emo, faces)
            print(f"derived  {emo}")
        faces[emo].save(ASSETS / f"sonny_{emo}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
