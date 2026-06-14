"""
EasyOCR score reader.

Reads the numeric score circle (0–9) for a zone straight off the frame. This is
the independent cross-check against the YOLO-derived hand value — if OCR and YOLO
disagree, the round is flagged low-confidence rather than trusted blindly.

First run downloads the EasyOCR detection/recognition models (~100 MB).
"""
import cv2
import easyocr
import numpy as np
from loguru import logger

from capture.roi_config import BANKER_SCORE_ROI, PLAYER_SCORE_ROI, scale_roi_for_frame
from recognition.device import has_cuda

_reader: easyocr.Reader | None = None


def get_reader() -> easyocr.Reader:
    global _reader
    if _reader is None:
        # EasyOCR's GPU path is CUDA-only; stay on CPU for MPS/CPU machines.
        _reader = easyocr.Reader(["en"], gpu=has_cuda())
        logger.info(f"EasyOCR reader initialized | gpu={has_cuda()}")
    return _reader


def _preprocess_score_crop(crop: np.ndarray) -> np.ndarray:
    """Grayscale, upscale and binarize the tiny score circle for better OCR."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (80, 80), interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return thresh


def read_score(frame: np.ndarray, zone: str) -> int | None:
    """Read the 0–9 score for a zone, or None if it can't be read confidently."""
    roi = PLAYER_SCORE_ROI if zone == "player" else BANKER_SCORE_ROI
    height, width = frame.shape[:2]
    roi = scale_roi_for_frame(roi, width, height)
    x1, y1, x2, y2 = roi
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        logger.warning(f"Empty score crop for zone '{zone}'.")
        return None

    proc = _preprocess_score_crop(crop)
    for _, text, conf in get_reader().readtext(proc, allowlist="0123456789", detail=1):
        text = text.strip()
        if text.isdigit() and conf > 0.5:
            score = int(text)
            if 0 <= score <= 9:
                logger.debug(f"OCR score [{zone}]: {score} (conf={conf:.2f})")
                return score

    logger.warning(f"OCR could not read score for zone: {zone}")
    return None
