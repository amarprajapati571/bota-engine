"""
Recognition pipeline: frame -> structured round result.
"""
import os
import uuid
from datetime import datetime, timezone

import numpy as np
from loguru import logger

from game_logic.baccarat_engine import card_value, compute_result
from game_logic.validator import validate
from recognition.card_recognizer import cards_in_deal_order, recognize_cards
from recognition.confidence_filter import filter_results


def _require_validation_passed() -> bool:
    return os.getenv("REQUIRE_VALIDATION_PASSED", "false").strip().lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


def _has_valid_side_counts(player_cards: list[str], banker_cards: list[str]) -> bool:
    return 2 <= len(player_cards) <= 3 and 2 <= len(banker_cards) <= 3


def _score_third_card_correction_enabled() -> bool:
    return os.getenv("SCORE_THIRD_CARD_CORRECTION", "true").strip().lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


def _rank_for_value(value: int) -> str | None:
    if value == 1:
        return "A"
    if 2 <= value <= 9:
        return str(value)
    return None


def _replace_rank(card: str, rank: str) -> str:
    if "_" not in card:
        suffix = card[-1:] if card[-1:].upper() in "CDHS" else ""
        return f"{rank}{suffix}" if suffix else card
    _, suit = card.split("_", 1)
    return f"{rank}_{suit}"


def _maybe_correct_player_third_card(frame: np.ndarray, player_cards: list[str]) -> list[str]:
    """
    Use the displayed player score to correct the sideways third-card value.

    If the score classifier is very confident, the third card value is implied
    by: final_score - first_two_value (mod 10). Suit is kept from YOLO.
    """
    if not _score_third_card_correction_enabled() or len(player_cards) != 3:
        return player_cards

    try:
        from recognition.score_classifier import read_score_digit, score_classifier_available

        if not score_classifier_available():
            return player_cards
        score, score_conf = read_score_digit(frame, "player")
    except Exception as exc:
        logger.debug(f"Player third-card correction skipped: {exc}")
        return player_cards

    min_conf = float(os.getenv("SCORE_THIRD_CARD_MIN_CONF", 0.98))
    if score is None or score_conf < min_conf:
        return player_cards

    first_two_value = (card_value(player_cards[0]) + card_value(player_cards[1])) % 10
    required_value = (score - first_two_value) % 10
    current_value = card_value(player_cards[2])
    if required_value == current_value:
        return player_cards

    rank = _rank_for_value(required_value)
    if rank is None:
        logger.info(
            "Player third-card value mismatch but target is 0, leaving rank unchanged | "
            f"cards={player_cards} score={score}"
        )
        return player_cards

    corrected = list(player_cards)
    corrected[2] = _replace_rank(corrected[2], rank)
    logger.warning(
        "Corrected player third card from score | "
        f"{player_cards[2]} -> {corrected[2]} | score={score} conf={score_conf:.3f}"
    )
    return corrected


def recognize_round(frame: np.ndarray) -> dict | None:
    """Run the full CV core on one frame."""
    round_id = (
        f"R-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    logger.info(f"Pipeline start | round_id={round_id}")

    player_det = recognize_cards(frame, zone="player")
    banker_det = recognize_cards(frame, zone="banker")

    player_visual_cards, player_ok, player_conf = filter_results(player_det)
    banker_visual_cards, banker_ok, banker_conf = filter_results(banker_det)
    player_cards = cards_in_deal_order(player_det)
    banker_cards = cards_in_deal_order(banker_det)
    player_cards = _maybe_correct_player_third_card(frame, player_cards)

    if not player_cards or not banker_cards:
        logger.warning(f"No cards detected | round_id={round_id}")
        return None
    if not _has_valid_side_counts(player_cards, banker_cards):
        logger.warning(
            f"Invalid baccarat card count | round_id={round_id} | "
            f"player_count={len(player_cards)} banker_count={len(banker_cards)} | "
            "expected 2-3 cards per side"
        )
        return None

    result = compute_result(player_cards, banker_cards)
    result["player_cards_visual_order"] = player_visual_cards
    result["banker_cards_visual_order"] = banker_visual_cards
    result["player_cards_deal_order"] = player_cards
    result["banker_cards_deal_order"] = banker_cards
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
        f"P={validated['score_player']} B={validated['score_banker']} "
        f"({validated['score_source']}) -> {result['outcome']} | "
        f"valid={validated['validation_passed']} ({validated['confidence_level']})"
    )
    if _require_validation_passed() and not validated["validation_passed"]:
        logger.warning(f"Skipping unvalidated round | id={round_id}")
        return None
    return validated
