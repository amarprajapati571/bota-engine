"""
YOLOv8 card recognition.

Input : a full game frame (BGR) and a zone ("player" / "banker").
Output: a list of {card, confidence, bbox}, sorted left-to-right (deal order).

The model is loaded lazily and cached. Class names come from your trained
weights and must follow the "<rank>_<suit>" convention the baccarat engine
expects (see game_logic/baccarat_engine.py).
"""
import os

import numpy as np
from loguru import logger
from ultralytics import YOLO

from capture.roi_config import BANKER_CARDS_ROI, PLAYER_CARDS_ROI
from recognition.device import resolve_device

_model: YOLO | None = None


def get_model() -> YOLO:
    global _model
    if _model is not None:
        return _model

    weights = os.getenv("MODEL_WEIGHTS_PATH", "./models/weights/best.pt")
    if not os.path.exists(weights):
        raise FileNotFoundError(
            f"Model weights not found at '{weights}'.\n"
            "Train a card detector (see README → 'Getting a model') and point "
            "MODEL_WEIGHTS_PATH at the resulting best.pt, or run `python main.py "
            "--demo` to exercise the game-logic pipeline without a model."
        )

    _model = YOLO(weights)
    logger.info(f"YOLOv8 model loaded: {weights} | classes={len(_model.names)}")
    return _model


def recognize_cards(frame: np.ndarray, zone: str) -> list[dict]:
    """Detect and classify cards in the given zone's ROI."""
    model = get_model()
    roi = PLAYER_CARDS_ROI if zone == "player" else BANKER_CARDS_ROI
    x1, y1, x2, y2 = roi
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        logger.warning(f"Empty crop for zone '{zone}' — check ROI calibration.")
        return []

    results = model.predict(
        source=crop,
        conf=float(os.getenv("MODEL_CONFIDENCE", 0.75)),
        device=resolve_device(),
        verbose=False,
    )

    detected: list[dict] = []
    for r in results:
        for box in r.boxes:
            detected.append({
                "card": model.names[int(box.cls[0])],
                "confidence": round(float(box.conf[0]), 4),
                "bbox": box.xyxy[0].tolist(),
            })

    # Sort left-to-right so the list matches the physical deal order.
    detected.sort(key=lambda d: d["bbox"][0])
    logger.debug(f"Zone '{zone}' detected: {[d['card'] for d in detected]}")
    return detected
