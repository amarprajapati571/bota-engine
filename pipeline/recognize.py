"""
Recognition pipeline: frame -> structured round result.

This is the CV core's orchestrator. Unlike the full production spec it has no
side effects (no Redis queue, no API push, no dedup) — it simply recognizes,
validates, and returns the result so a caller can print or store it.
"""
import uuid
from datetime import datetime, timezone

import numpy as np
from loguru import logger

from game_logic.baccarat_engine import compute_result
from game_logic.validator import validate
from recognition.card_recognizer import recognize_cards
from recognition.confidence_filter import filter_results


def recognize_round(frame: np.ndarray) -> dict | None:
    """
    Run the full CV core on one frame.

    Returns the enriched round dict, or None if no cards were detected.
    """
    round_id = (
        f"R-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    logger.info(f"Pipeline start | round_id={round_id}")

    player_det = recognize_cards(frame, zone="player")
    banker_det = recognize_cards(frame, zone="banker")

    player_cards, player_ok, player_conf = filter_results(player_det)
    banker_cards, banker_ok, banker_conf = filter_results(banker_det)

    if not player_cards or not banker_cards:
        logger.warning(f"No cards detected | round_id={round_id}")
        return None

    result = compute_result(player_cards, banker_cards)
    validated = validate(frame, result)
    validated.update({
        "round_id": round_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "player_conf": player_conf,
        "banker_conf": banker_conf,
        "all_confident": player_ok and banker_ok,
    })

    logger.success(
        f"Round done | id={round_id} | "
        f"P={result['player_value']} B={result['banker_value']} -> {result['outcome']} | "
        f"valid={validated['validation_passed']} ({validated['confidence_level']})"
    )
    return validated
