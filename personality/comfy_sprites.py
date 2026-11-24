"""Generate Sonny expression sprites with the local ComfyUI server.

    python -m personality.comfy_sprites                 # all 50
    python -m personality.comfy_sprites --only crying,smug --denoise 0.6

Img2img (Juggernaut XL) from the neutral base so every face is the same
robot; output keyed to transparent PNGs in personality/assets/faces/.
Talks to ComfyUI over HTTP only (http://127.0.0.1:8188), nothing else.
"""
from __future__ import annotations

import argparse
import io
import json
import time
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

from personality.make_sprites import chroma_key

HERE = Path(__file__).resolve().parent
BASE = HERE / "assets" / "base_greenscreen.png"
OUT = HERE / "assets" / "faces"
RAW = HERE / "assets" / "faces_raw"
SERVER = "http://127.0.0.1:8188"
CKPT = "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"

STYLE = ("photo of Sonny the pale white humanoid robot from the movie I Robot, bald smooth "
         "translucent white synthetic skin, blue eyes, black cable neck pistons, head and shoulders "
         "portrait, centered, solid flat bright green background, film still, sharp focus, ")
NEG = ("human skin tone, hair, eyebrows hair, beard, cartoon, anime, drawing, text, watermark, "
       "extra head, deformed face, blurry, background objects, frame, border")

# name -> expression prompt. Ordered roughly by how often the dialogue uses them.
EMOTIONS = {
    "neutral": "neutral deadpan expression, slightly unimpressed",
    "smug": "extremely smug expression, one eyebrow raised, smirking",
    "cocky": "cocky grin, chin up, looking down at the viewer",
    "panic": "panicked, eyes wide open, mouth open screaming, sweating",
    "shocked": "shocked, jaw dropped, eyes very wide",
    "crying": "crying hard, tears streaming down cheeks, mouth wobbling",
    "sobbing_laugh": "laughing so hard he is crying, eyes squeezed shut, tears, wide open mouth",
    "laughing": "laughing loudly, big open mouth smile, eyes squinting",
    "irritated": "irritated, heavy frown, glaring sideways",
    "furious": "furious, teeth clenched, veins, angry glare",
    "disgusted": "disgusted, nose wrinkled, upper lip raised, recoiling",
    "confused": "confused, head tilted, one eyebrow up, squinting",
    "thinking": "thinking hard, eyes looking up, lips pursed",
    "side_eye": "side eye, eyes looking hard to the side, suspicious, flat mouth",
    "suspicious": "suspicious narrowed eyes, leaning in, skeptical",
    "deadinside": "dead inside, empty thousand yard stare, expressionless",
    "defeated": "defeated, head drooping, sad glossy eyes, single tear",
    "embarrassed": "embarrassed, awkward grimace smile, looking away, blushing cheeks",
    "cringe": "cringing hard, teeth clenched grimace, eyes half closed",
    "vengeful": "vengeful villain stare from under the brow, cold thin smile",
    "evil_grin": "evil wide grin, menacing eyes, villain",
    "delusional": "delusional unhinged huge grin, eyes unfocused",
    "unhinged": "unhinged manic laugh, eyes bulging, wild",
    "sleepy": "sleepy, eyelids half closed, bored, yawning slightly",
    "yawning": "yawning wide, eyes closed, bored",
    "bored": "bored, resting face, eyes half lidded, unimpressed",
    "skeptical": "skeptical, one eyebrow raised high, mouth pulled to one side",
    "pouting": "pouting, lips pushed out, sulking",
    "sad": "sad, downturned mouth, puppy eyes",
    "heartbroken": "heartbroken, trembling lip, watery eyes looking up",
    "hopeful": "hopeful, eyebrows raised, small nervous smile",
    "nervous": "nervous, sweating, forced awkward smile",
    "scared": "scared, eyes wide, shrinking back, mouth tight",
    "terrified": "terrified, screaming in horror, eyes huge",
    "relieved": "relieved, exhaling, eyes closed, soft smile",
    "proud": "proud, chest out, confident satisfied smile",
    "smirk": "subtle smirk, half smile, knowing look",
    "wink": "winking one eye, cheeky smile",
    "kissy": "blowing a kiss, lips puckered, eyes closed",
    "tongue_out": "sticking tongue out, mocking, playful",
    "grimace": "grimace, showing clenched teeth, eyes wide",
    "speechless": "speechless, mouth slightly open, blank stare, frozen",
    "facepalm_face": "pained expression, eyes shut tight, wincing",
    "rage": "screaming in rage, mouth wide open, angry eyes",
    "judging": "judging, chin down, eyes looking up disapprovingly",
    "starstruck": "starstruck amazed, sparkling wide eyes, open smile",
    "blank": "completely blank stare, no emotion, eyes straight ahead",
    "giggling": "giggling, hand-free, closed eyes, small laugh",
    "menacing": "menacing glare, lowered head, dark shadows on eyes",
    "dizzy": "dizzy, crossed eyes, wobbly open mouth",
}


def _post(path: str, data: bytes, ctype: str) -> dict:
    req = urllib.request.Request(SERVER + path, data=data, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def upload(path: Path) -> str:
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + path.read_bytes() + \
           f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
    return _post("/upload/image", body, f"multipart/form-data; boundary={boundary}")["name"]


def workflow(image: str, prompt: str, seed: int, denoise: float) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image}},
        "3": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": STYLE + prompt, "clip": ["1", 1]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["1", 1]}},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["3", 0],
            "seed": seed, "steps": 30, "cfg": 6.0, "sampler_name": "dpmpp_2m",
            "scheduler": "karras", "denoise": denoise}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "sonny_face"}},
    }


def run(image: str, prompt: str, seed: int, denoise: float) -> Image.Image:
    pid = _post("/prompt", json.dumps({"prompt": workflow(image, prompt, seed, denoise)}).encode(),
                "application/json")["prompt_id"]
    while True:
        time.sleep(1.0)
        with urllib.request.urlopen(f"{SERVER}/history/{pid}", timeout=30) as r:
            hist = json.loads(r.read())
        if pid in hist:
            if hist[pid].get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(hist[pid]["status"])[:500])
            img = hist[pid]["outputs"]["8"]["images"][0]
            url = f"{SERVER}/view?filename={img['filename']}&subfolder={img['subfolder']}&type={img['type']}"
            with urllib.request.urlopen(url, timeout=60) as r:
                return Image.open(io.BytesIO(r.read())).convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--denoise", type=float, default=0.62)
    ap.add_argument("--seed", type=int, default=1804)
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    name = upload(BASE)
    todo = [n for n in (args.only.split(",") if args.only else EMOTIONS) if n]
    for i, emo in enumerate(todo):
        if args.skip_existing and (OUT / f"{emo}.png").exists():
            continue
        t0 = time.time()
        img = run(name, EMOTIONS[emo], args.seed + i, args.denoise)
        img.save(RAW / f"{emo}.png")
        chroma_key(img).save(OUT / f"{emo}.png")
        print(f"[{i + 1}/{len(todo)}] {emo:14s} {time.time() - t0:5.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
