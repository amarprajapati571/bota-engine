"""
Confidence filter for card detections.

Splits a zone's detections into card names plus a summary of how trustworthy the
recognition was, so the pipeline can decide whether to trust the round.
"""
import os

from loguru import logger


def _min_confidence() -> float:
    return float(os.getenv("MODEL_CONFIDENCE", 0.75))


def filter_results(detections: list[dict]) -> tuple[list[str], bool, float]:
    """
    Returns:
        cards          : list of card-name strings (deal order preserved)
        all_confident  : True iff every detection is at/above the threshold
        avg_confidence : mean confidence (0.0 when there are no detections)
    """
    if not detections:
        return [], False, 0.0

    threshold = _min_confidence()
    cards = [d["card"] for d in detections]
    low_conf = [d for d in detections if d["confidence"] < threshold]
    avg_conf = sum(d["confidence"] for d in detections) / len(detections)

    if low_conf:
        logger.warning(
            "Low-confidence cards: "
            f"{[(d['card'], d['confidence']) for d in low_conf]} (min={threshold})"
        )

    return cards, not low_conf, round(avg_conf, 4)
