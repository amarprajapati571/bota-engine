"""
ROI configuration — the single source of truth for every pixel coordinate.

By default the WHOLE monitor is captured (CAPTURE_FULLSCREEN), so the ROIs below
are in full-screen pixel coordinates. They are placeholders: run
`python main.py --calibrate` against your own screen and update them (here or via
the matching .env variables) until the boxes line up in the saved annotated
screenshot.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ── Capture region ───────────────────────────────────────────────────────────
# By default the entire monitor is captured. Turn CAPTURE_FULLSCREEN off to grab
# only the GAME_MONITOR rectangle instead (then ROIs are relative to that crop).
CAPTURE_FULLSCREEN = _bool("CAPTURE_FULLSCREEN", True)
CAPTURE_MONITOR_INDEX = _int("CAPTURE_MONITOR_INDEX", 1)   # 1 = primary display, 0 = all monitors

GAME_MONITOR = {
    "top": _int("GAME_MONITOR_TOP", 0),
    "left": _int("GAME_MONITOR_LEFT", 0),
    "width": _int("GAME_MONITOR_WIDTH", 880),
    "height": _int("GAME_MONITOR_HEIGHT", 500),
}


def resolve_capture_region(sct) -> dict:
    """
    The region to grab: the full monitor when CAPTURE_FULLSCREEN is on, otherwise
    the GAME_MONITOR rectangle. `sct` is an mss instance (passed in so this module
    need not import mss).
    """
    if CAPTURE_FULLSCREEN:
        m = sct.monitors[CAPTURE_MONITOR_INDEX]
        return {"top": m["top"], "left": m["left"], "width": m["width"], "height": m["height"]}
    return dict(GAME_MONITOR)

# ── WIN badge (gold circle, centre screen) — the capture trigger ─────────────
WIN_BADGE_ROI = (370, 310, 480, 405)   # x1, y1, x2, y2
WIN_BADGE_TEXT_ROI = (375, 330, 475, 390)
GOLD_HSV_LOWER = (15, 100, 150)        # HSV lower bound for "gold"
GOLD_HSV_UPPER = (35, 255, 255)        # HSV upper bound for "gold"
GOLD_PIXEL_THRESHOLD = _float("WIN_BADGE_GOLD_THRESHOLD", 0.12)

# ── Card zones (cropped before running YOLO) ─────────────────────────────────
PLAYER_CARDS_ROI = (120, 295, 370, 425)
BANKER_CARDS_ROI = (495, 295, 760, 425)

# ── Score circles (0–9 total) read by OCR for cross-validation ───────────────
PLAYER_SCORE_ROI = (340, 298, 380, 322)
BANKER_SCORE_ROI = (490, 298, 530, 322)

# ── Capture loop tuning ──────────────────────────────────────────────────────
CAPTURE_FPS = _int("CAPTURE_FPS", 5)
CAPTURE_COOLDOWN_SECS = _float("CAPTURE_COOLDOWN_SECONDS", 4)
