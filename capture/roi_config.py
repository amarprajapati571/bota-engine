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

# ── WIN badge (gold "WIN PLAYER/BANKER" circle, bottom-centre) — the trigger ─
# Coordinates below are for seam.zisego.com baccarat at 1920x1080, full-screen
# capture. Verify with `--calibrate` (annotated overlay) and nudge if needed.
WIN_BADGE_ROI = (900, 798, 1086, 942)   # x1, y1, x2, y2 — the gold circle
WIN_BADGE_TEXT_ROI = (905, 850, 1080, 905)
GOLD_HSV_LOWER = (15, 100, 150)        # HSV lower bound for "gold"
GOLD_HSV_UPPER = (35, 255, 255)        # HSV upper bound for "gold"
GOLD_PIXEL_THRESHOLD = _float("WIN_BADGE_GOLD_THRESHOLD", 0.12)

# ── Card zones (cropped before running YOLO) ─────────────────────────────────
PLAYER_CARDS_ROI = (545, 778, 810, 972)    # the two Player cards (bottom-left-centre)
BANKER_CARDS_ROI = (1160, 778, 1432, 972)  # the two Banker cards (bottom-right-centre)

# ── Score circles (0–9 total) read by OCR for cross-validation ───────────────
PLAYER_SCORE_ROI = (816, 744, 858, 785)    # the "7" circle at the right of PLAYER banner
BANKER_SCORE_ROI = (1130, 744, 1172, 785)  # the "6" circle at the left of BANKER banner

# ── Capture loop tuning ──────────────────────────────────────────────────────
CAPTURE_FPS = _int("CAPTURE_FPS", 5)
CAPTURE_COOLDOWN_SECS = _float("CAPTURE_COOLDOWN_SECONDS", 4)
