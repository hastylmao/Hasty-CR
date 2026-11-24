"""Between-battle navigation, ported from the old bot (scripts/cr_bot.py).

The studio's bot got through lobby -> battle -> end screen -> rewards -> lobby
unattended; this is the same logic, minus its vision battle reader (the
memory reader replaces that):

  lobby          BuildABot's screen hash says "lobby" AND the orange Battle
                 button is there (mumu_overnight_bot.home_guard)  -> tap Battle
  end_of_game /  BuildABot's screen hash; tap that screen's own button
  bypass_end     (Screens.*.click_xy, 720p x 1.5)
  unknown        reward_screen (empty top band = chest / card reveal) -> tap
                 to advance; connection_lost -> RELOAD; after 15 s a popup's
                 close button (popup_guard); after 75 s relaunch Clash Royale

Each of those tests is the old bot's, measured there; none is re-guessed
here. The colour-only checks this replaces mistook the gold coin bag on the
win screen for the Battle button (2026-10-10).
"""
from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts")]

import connection_lost  # noqa: E402
import popup_guard  # noqa: E402
import reward_screen  # noqa: E402

ADB = r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe"
SCREEN_DIR = ROOT / "vendor" / "ClashRoyaleBuildABot" / "clashroyalebuildabot" / "images" / "screen"
HOME_BATTLE = (540, 1490)                       # mumu_overnight_bot.HOME_BATTLE
# BuildABot Screens (720x1280 regions and click points), copied as data.
SCREENS = {
    "in_game": ((148, 1254, 163, 1274), None),
    "lobby": ((424, 126, 506, 181), (360, 1000)),
    "end_of_game": ((379, 1122, 560, 1201), (243, 1158)),
    "bypass_end_of_game": ((269, 1123, 451, 1201), (360, 1161)),
}
UNKNOWN_POPUP_SECONDS = 15                      # cr_bot.py
UNKNOWN_RECOVER_SECONDS = 75
UNKNOWN_RECOVER_COOLDOWN = 150


def _hash(img):
    return np.asarray(img.resize((8, 8), Image.Resampling.BILINEAR), dtype=np.float32).flatten()


_REF = {name: _hash(Image.open(SCREEN_DIR / f"{name}.jpg")) for name in SCREENS}


def classify(small):
    """BuildABot's ScreenDetector.run: nearest reference crop under threshold 30."""
    best, best_diff = "unknown", 30.0
    w, h = small.size
    for name, (ltrb, _) in SCREENS.items():
        box = (int(ltrb[0] * w / 720), int(ltrb[1] * h / 1280),
               int(ltrb[2] * w / 720), int(ltrb[3] * h / 1280))
        diff = float(np.mean(np.abs(_hash(small.crop(box)) - _REF[name])))
        if diff < best_diff:
            best, best_diff = name, diff
    return best


def capture(serial):
    """Raw screencap (header, then RGBA). The PNG form came back truncated
    over exec-out on 2026-10-10 ("image file is truncated")."""
    for _ in range(3):
        raw = subprocess.run([ADB, "-s", serial, "exec-out", "screencap"],
                             capture_output=True, timeout=15).stdout
        if len(raw) < 16:
            continue
        w, h = (int(v) for v in np.frombuffer(raw[:8], "<u4"))
        hdr = len(raw) - w * h * 4
        if 0 <= hdr <= 16:
            break
    else:
        raise OSError("screencap failed 3 times")
    rgba = np.frombuffer(raw[hdr:], np.uint8).reshape(h, w, 4)
    full = Image.fromarray(rgba[:, :, :3].copy(), "RGB")
    if full.size != (1080, 1920):
        full = full.resize((1080, 1920))
    return full, full.resize((368, 652))


def home_guard(full):
    """mumu_overnight_bot.home_guard: the orange Battle button fills its region."""
    roi = np.asarray(full)[1380:1600, 350:730].astype(np.int16)
    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    orange = (r > 180) & (g > 80) & (g < 210) & (b < 100) & (r > g * 1.25)
    return float(orange.mean()) > 0.35


END_OK = (540, 1688)


def end_ok_button(full):
    """The blue OK button of a challenge end screen (see Navigator.step)."""
    roi = np.asarray(full)[1640:1740, 400:680].astype(np.int16)
    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    blue = (b > 230) & (g > 130) & (g < 210) & (r < 130)
    return float(blue.mean()) > 0.4


def tap(serial, xy):
    subprocess.run([ADB, "-s", serial, "shell", "input", "tap", str(xy[0]), str(xy[1])],
                   capture_output=True, timeout=10)


class Navigator:
    """Call step() whenever no battle is being read. Returns a log line or None."""

    def __init__(self, serial, queue=True):
        self.serial, self.queue = serial, queue
        now = time.monotonic()
        self.last_nav = self.last_reward = self.last_reload = 0.0
        self.last_popup = self.last_recover = 0.0
        self.unknown_since = now
        self.reward_taps = 0
        self.screen = None

    def step(self):
        full, small = capture(self.serial)
        screen = classify(small)
        now = time.monotonic()
        note = None
        if screen != self.screen:
            note = f"    screen {self.screen} -> {screen}"
            self.screen = screen
        if screen == "in_game":
            self.unknown_since = now
            return note
        if screen == "lobby":
            self.unknown_since, self.reward_taps = now, 0
            if self.queue and now - self.last_nav > 5 and home_guard(full):
                tap(self.serial, HOME_BATTLE)
                self.last_nav = now
                return "    tapped Battle"
            return note
        if screen in ("end_of_game", "bypass_end_of_game"):
            self.unknown_since = now
            if self.queue and now - self.last_nav > 4:
                xy = SCREENS[screen][1]
                tap(self.serial, (round(xy[0] * 1.5), round(xy[1] * 1.5)))
                self.last_nav = now
                return f"    tapped {screen} button"
            return note
        # unknown
        # Grand Challenge (and other event) end screens have a single blue OK
        # button and no Play Again, so the BuildABot hashes call them unknown.
        # Measured on instance 3, 2026-11-18: button spans x 398-681, y ~1630-1740,
        # 65% of the box below matches this blue; 2% of the whole screen does.
        if self.queue and now - self.last_nav > 4 and end_ok_button(full):
            tap(self.serial, END_OK)
            self.last_nav = self.unknown_since = now
            return "    tapped end-screen OK"
        if now - self.last_reward > 1.5 and reward_screen.is_reward_screen(full):
            self.last_reward = now
            self.reward_taps += 1
            spot = reward_screen.advance_point(self.reward_taps)
            tap(self.serial, spot)
            self.unknown_since = now
            return f"    reward screen: tap #{self.reward_taps} at {spot}"
        spot = connection_lost.find_reload(full)
        if spot is not None and now - self.last_reload > 8:
            self.last_reload = now
            tap(self.serial, spot)
            self.unknown_since = now
            return f"    connection lost: tapped RELOAD at {spot}"
        if now - self.unknown_since > UNKNOWN_POPUP_SECONDS and now - self.last_popup > 25:
            self.last_popup = now
            spot = popup_guard.find_close_button(full)
            if spot is not None:
                tap(self.serial, spot)
                return f"    popup: tapped close at {spot}"
            return "    popup: no close button found"
        if (now - self.unknown_since > UNKNOWN_RECOVER_SECONDS
                and now - self.last_recover > UNKNOWN_RECOVER_COOLDOWN):
            self.last_recover = now
            subprocess.run([ADB, "-s", self.serial, "shell", "monkey", "-p",
                            "com.supercell.clashroyale", "-c",
                            "android.intent.category.LAUNCHER", "1"],
                           capture_output=True, timeout=20)
            return "    stuck 75 s on an unknown screen: relaunched Clash Royale"
        return note
