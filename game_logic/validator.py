"""
Cross-validation layer.

Compares the YOLO-derived hand values against two independent signals:
  1. the OCR-read score circles on screen, and
  2. whether the observed card counts obey the baccarat drawing rules.

A mismatch on either is a strong hint that a card was misread.
"""
from loguru import logger

from game_logic.baccarat_engine import is_rules_consistent
from recognition.ocr_reader import read_score


def validate(frame, computed: dict) -> dict:
    """Enrich a computed result with OCR/rule cross-checks and a confidence level."""
    ocr_player = read_score(frame, "player")
    ocr_banker = read_score(frame, "banker")

    player_match = ocr_player is not None and ocr_player == computed["player_value"]
    banker_match = ocr_banker is not None and ocr_banker == computed["banker_value"]
    rules_ok = is_rules_consistent(computed["player_cards"], computed["banker_cards"])

    validation_passed = player_match and banker_match
    confidence_level = "HIGH" if (validation_passed and rules_ok) else "LOW"

    if confidence_level == "HIGH":
        logger.success(
            f"Validation PASSED | P={computed['player_value']} B={computed['banker_value']}"
        )
    else:
        logger.warning(
            "Validation FAILED | "
            f"YOLO P={computed['player_value']} B={computed['banker_value']} | "
            f"OCR P={ocr_player} B={ocr_banker} | rules_ok={rules_ok}"
        )

    return {
        **computed,
        "ocr_player_score": ocr_player,
        "ocr_banker_score": ocr_banker,
        "player_match": player_match,
        "banker_match": banker_match,
        "rules_consistent": rules_ok,
        "validation_passed": validation_passed,
        "confidence_level": confidence_level,
    }
