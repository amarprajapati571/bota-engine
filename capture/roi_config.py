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


def _roi(name: str, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """
    Read an ROI from either ROI_NAME=x1,y1,x2,y2 or ROI_NAME_X1 etc.
    This keeps calibration changes in .env instead of requiring code edits.
    """
    raw = os.getenv(name)
    if raw:
        parts = [p.strip() for p in raw.replace(" ", "").split(",")]
        if len(parts) != 4:
            raise ValueError(f"{name} must be four comma-separated integers: x1,y1,x2,y2")
        return tuple(int(p) for p in parts)  # type: ignore[return-value]

    x1, y1, x2, y2 = default
    return (
        _int(f"{name}_X1", x1),
        _int(f"{name}_Y1", y1),
        _int(f"{name}_X2", x2),
        _int(f"{name}_Y2", y2),
    )


# ── Capture region ───────────────────────────────────────────────────────────
ROI_BASE_WIDTH = _int("ROI_BASE_WIDTH", 1920)
ROI_BASE_HEIGHT = _int("ROI_BASE_HEIGHT", 1080)


def scale_roi_for_frame(
    roi: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    """Scale a full-screen ROI to a saved screenshot with a different size."""
    if frame_width == ROI_BASE_WIDTH and frame_height == ROI_BASE_HEIGHT:
        return roi

    sx = frame_width / ROI_BASE_WIDTH
    sy = frame_height / ROI_BASE_HEIGHT
    x1, y1, x2, y2 = roi
    scaled = (
        int(round(x1 * sx)),
        int(round(y1 * sy)),
        int(round(x2 * sx)),
        int(round(y2 * sy)),
    )
    return (
        max(0, min(frame_width, scaled[0])),
        max(0, min(frame_height, scaled[1])),
        max(0, min(frame_width, scaled[2])),
        max(0, min(frame_height, scaled[3])),
    )


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
WIN_BADGE_ROI = _roi("WIN_BADGE_ROI", (906, 784, 1103, 927))   # x1, y1, x2, y2
WIN_BADGE_TEXT_ROI = _roi("WIN_BADGE_TEXT_ROI", (930, 845, 1085, 898))
GOLD_HSV_LOWER = (15, 100, 150)        # HSV lower bound for "gold"
GOLD_HSV_UPPER = (35, 255, 255)        # HSV upper bound for "gold"
GOLD_PIXEL_THRESHOLD = _float("WIN_BADGE_GOLD_THRESHOLD", 0.12)

# ── Card zones (cropped before running YOLO) ─────────────────────────────────
PLAYER_CARDS_ROI = _roi("PLAYER_CARDS_ROI", (340, 780, 850, 997))
BANKER_CARDS_ROI = _roi("BANKER_CARDS_ROI", (1157, 782, 1643, 992))

# ── Score circles (0–9 total) read by OCR for cross-validation ───────────────
PLAYER_SCORE_ROI = _roi("PLAYER_SCORE_ROI", (817, 711, 887, 781))
BANKER_SCORE_ROI = _roi("BANKER_SCORE_ROI", (1129, 716, 1189, 777))

# Marked areas saved by scripts/extract_frames.py --crop. These are useful for
# labeling cards, winner badge classes, and score-digit crops separately.
MARKED_CROP_ROIS = {
    "player_cards": PLAYER_CARDS_ROI,
    "banker_cards": BANKER_CARDS_ROI,
    "winner_badge": WIN_BADGE_ROI,
    "player_score": PLAYER_SCORE_ROI,
    "banker_score": BANKER_SCORE_ROI,
}

# ── Capture loop tuning ──────────────────────────────────────────────────────
CAPTURE_FPS = _int("CAPTURE_FPS", 5)
CAPTURE_COOLDOWN_SECS = _float("CAPTURE_COOLDOWN_SECONDS", 4)
