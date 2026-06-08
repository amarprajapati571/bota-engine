"""
ROI configuration — the single source of truth for every pixel coordinate.

All values assume an 880x500 game window. They are placeholders: run
`python main.py --calibrate` against your own window and update them (here or
via the matching .env variables) until the boxes line up in the saved
annotated screenshot.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


# ── Game window region passed to mss.grab() ──────────────────────────────────
GAME_MONITOR = {
    "top": _int("GAME_MONITOR_TOP", 0),
    "left": _int("GAME_MONITOR_LEFT", 0),
    "width": _int("GAME_MONITOR_WIDTH", 880),
    "height": _int("GAME_MONITOR_HEIGHT", 500),
}

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
