"""
Interactive calibration helper.

Open your game window, then run `python main.py --calibrate`. It saves two
images in the project root:

  1. calibration_full.png            — the whole primary display, so you can read
                                       off GAME_MONITOR_TOP/LEFT/WIDTH/HEIGHT.
  2. calibration_region_annotated.png — just the configured GAME_MONITOR region
                                       with every ROI box drawn on it, so you can
                                       confirm the card/badge/score boxes align.

Iterate: tweak roi_config.py (or the .env values), re-run, repeat until the
boxes sit exactly on the cards, the WIN badge, and the score circles.
"""
import os

import cv2
import mss
import numpy as np

from capture.roi_config import (
    BANKER_CARDS_ROI,
    BANKER_SCORE_ROI,
    GAME_MONITOR,
    PLAYER_CARDS_ROI,
    PLAYER_SCORE_ROI,
    WIN_BADGE_ROI,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FULL_PATH = os.path.join(PROJECT_ROOT, "calibration_full.png")
REGION_PATH = os.path.join(PROJECT_ROOT, "calibration_region_annotated.png")

# label -> (roi, BGR colour)
_ROIS = {
    "WIN_BADGE": (WIN_BADGE_ROI, (0, 215, 255)),      # gold
    "PLAYER_CARDS": (PLAYER_CARDS_ROI, (0, 200, 0)),  # green
    "BANKER_CARDS": (BANKER_CARDS_ROI, (200, 0, 0)),  # blue
    "PLAYER_SCORE": (PLAYER_SCORE_ROI, (0, 200, 255)),  # orange
    "BANKER_SCORE": (BANKER_SCORE_ROI, (200, 0, 200)),  # purple
}


def draw_rois(image: np.ndarray) -> np.ndarray:
    """Overlay every configured ROI box (coords are relative to GAME_MONITOR)."""
    img = image.copy()
    for label, (roi, color) in _ROIS.items():
        x1, y1, x2, y2 = roi
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, label, (x1, max(y1 - 5, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    return img


def capture_and_save() -> None:
    with mss.mss() as sct:
        full = np.array(sct.grab(sct.monitors[1]))
        full_bgr = cv2.cvtColor(full, cv2.COLOR_BGRA2BGR)

        region = np.array(sct.grab(GAME_MONITOR))
        region_bgr = cv2.cvtColor(region, cv2.COLOR_BGRA2BGR)

    cv2.imwrite(FULL_PATH, full_bgr)
    cv2.imwrite(REGION_PATH, draw_rois(region_bgr))

    print(f"Primary display : {full_bgr.shape[1]} x {full_bgr.shape[0]}")
    print(f"GAME_MONITOR    : {GAME_MONITOR}")
    print(f"Saved full screen     -> {FULL_PATH}")
    print(f"Saved annotated region -> {REGION_PATH}")
    if region_bgr.mean() < 2.0:
        print("\n[!] Region looks blank. On macOS, grant Screen Recording "
              "permission to your terminal and try again.")
    print("\nNext: open the annotated image, adjust ROIs in capture/roi_config.py, re-run.")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, PROJECT_ROOT)
    capture_and_save()
