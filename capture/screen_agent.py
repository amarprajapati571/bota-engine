"""
Screen agent — grabs the game window and fires a callback when the gold WIN
badge appears in the centre region.

macOS note: screen capture requires Screen Recording permission
(System Settings → Privacy & Security → Screen Recording). Without it, mss
returns black frames; `_looks_blank()` warns when that happens.
"""
import time

import cv2
import mss
import numpy as np
from loguru import logger

from capture.roi_config import (
    CAPTURE_COOLDOWN_SECS,
    CAPTURE_FPS,
    GAME_MONITOR,
    GOLD_HSV_LOWER,
    GOLD_HSV_UPPER,
    GOLD_PIXEL_THRESHOLD,
    WIN_BADGE_ROI,
)

_last_trigger_time = 0.0
_blank_warned = False


def _grab(sct, region: dict) -> np.ndarray:
    """Grab a region with an existing mss instance and return a BGR array."""
    raw = sct.grab(region)
    return cv2.cvtColor(np.array(raw), cv2.COLOR_BGRA2BGR)


def capture_frame() -> np.ndarray:
    """Grab a single game-window frame (BGR). Opens its own mss instance."""
    with mss.mss() as sct:
        return _grab(sct, GAME_MONITOR)


def _looks_blank(frame: np.ndarray) -> bool:
    """Heuristic: an (almost) all-black frame usually means missing permission."""
    return bool(frame.mean() < 2.0)


def is_win_badge_visible(frame: np.ndarray) -> tuple[bool, float]:
    """
    Detect the gold WIN badge in the centre ROI.

    Returns (badge_present, gold_ratio). The ratio is the fraction of pixels in
    the ROI that fall inside the gold HSV band — useful for tuning the threshold.
    """
    x1, y1, x2, y2 = WIN_BADGE_ROI
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return False, 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(GOLD_HSV_LOWER), np.array(GOLD_HSV_UPPER))
    ratio = cv2.countNonZero(mask) / float((x2 - x1) * (y2 - y1))
    return ratio >= GOLD_PIXEL_THRESHOLD, ratio


def should_trigger(badge_visible: bool) -> bool:
    """Debounce: only allow one trigger per cooldown window."""
    global _last_trigger_time
    now = time.time()
    if badge_visible and (now - _last_trigger_time) > CAPTURE_COOLDOWN_SECS:
        _last_trigger_time = now
        return True
    return False


def run_capture_loop(on_trigger_callback) -> None:
    """
    Main loop. Calls `on_trigger_callback(frame)` once per WIN-badge appearance.
    Blocks until interrupted with Ctrl-C.
    """
    global _blank_warned
    logger.info(f"Screen agent started | {CAPTURE_FPS} fps | region={GAME_MONITOR}")
    sleep_interval = 1.0 / max(CAPTURE_FPS, 1)

    with mss.mss() as sct:
        while True:
            try:
                frame = _grab(sct, GAME_MONITOR)

                if _looks_blank(frame) and not _blank_warned:
                    logger.warning(
                        "Captured frame is blank/black. On macOS, grant Screen "
                        "Recording permission to your terminal and restart."
                    )
                    _blank_warned = True

                badge_visible, ratio = is_win_badge_visible(frame)
                if should_trigger(badge_visible):
                    logger.success(f"WIN badge detected | gold_ratio={ratio:.3f}")
                    on_trigger_callback(frame)

                time.sleep(sleep_interval)
            except KeyboardInterrupt:
                logger.info("Screen agent stopped by user.")
                break
            except Exception as exc:  # keep the loop alive on transient errors
                logger.error(f"Capture error: {exc}")
                time.sleep(1)
