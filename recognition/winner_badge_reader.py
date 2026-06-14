"""
Winner-badge outcome reader.

The card model only sees cards. This lightweight reader checks the result badge
ROI and infers PLAYER/BANKER/TIE from the colored ribbon/accent pixels.
"""
import cv2
import numpy as np
from loguru import logger

from capture.roi_config import WIN_BADGE_ROI, scale_roi_for_frame


def read_winner_badge(frame: np.ndarray) -> tuple[str | None, float]:
    """Return (outcome, confidence), or (None, 0.0) when no badge is readable."""
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = scale_roi_for_frame(WIN_BADGE_ROI, width, height)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        logger.warning("Empty winner badge crop.")
        return None, 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    # Ignore dark/gray pixels from the badge body and count only saturated color.
    red = (((hue < 10) | (hue > 170)) & (sat > 80) & (val > 70)).mean()
    blue = ((hue > 90) & (hue < 135) & (sat > 60) & (val > 50)).mean()
    green = ((hue > 35) & (hue < 85) & (sat > 50) & (val > 50)).mean()

    scores = {
        "BANKER": float(red),
        "PLAYER": float(blue),
        "TIE": float(green),
    }
    outcome, confidence = max(scores.items(), key=lambda item: item[1])
    if confidence < 0.01:
        return None, 0.0

    logger.debug(f"Winner badge: {outcome} | scores={scores}")
    return outcome, round(confidence, 4)
