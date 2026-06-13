"""
Score-bubble classifier.

Lightweight alternative to OCR for the small 0-9 score circles. Used as a
validation/correction signal, especially for sideways third cards.
"""
import os

import numpy as np
from loguru import logger
from ultralytics import YOLO

from capture.roi_config import BANKER_SCORE_ROI, PLAYER_SCORE_ROI
from recognition.device import resolve_device

_score_model: YOLO | None = None


def _weights_path() -> str:
    return os.getenv("SCORE_MODEL_WEIGHTS_PATH", "./models/weights/score_digits.pt")


def score_classifier_available() -> bool:
    return os.path.exists(_weights_path())


def get_score_model() -> YOLO:
    global _score_model
    if _score_model is not None:
        return _score_model

    weights = _weights_path()
    if not os.path.exists(weights):
        raise FileNotFoundError(f"Score classifier weights not found: {weights}")
    _score_model = YOLO(weights)
    logger.info(f"Score classifier loaded: {weights} | classes={len(_score_model.names)}")
    return _score_model


def read_score_digit(frame: np.ndarray, zone: str) -> tuple[int | None, float]:
    """Return (digit, confidence), or (None, 0.0) when unavailable."""
    roi = PLAYER_SCORE_ROI if zone == "player" else BANKER_SCORE_ROI
    x1, y1, x2, y2 = roi
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        logger.warning(f"Empty score crop for zone '{zone}'.")
        return None, 0.0

    result = get_score_model().predict(
        source=crop,
        device=resolve_device(),
        verbose=False,
        imgsz=int(os.getenv("SCORE_CLASSIFIER_IMGSZ", 96)),
    )[0]
    if result.probs is None:
        return None, 0.0

    cls_idx = int(result.probs.top1)
    conf = float(result.probs.top1conf)
    label = str(get_score_model().names[cls_idx])
    if label.isdigit():
        digit = int(label)
        if 0 <= digit <= 9:
            logger.debug(f"Score classifier [{zone}]: {digit} (conf={conf:.3f})")
            return digit, conf
    return None, conf
