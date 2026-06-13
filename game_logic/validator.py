"""
Cross-validation layer.
"""
import os

from loguru import logger

from game_logic.baccarat_engine import is_rules_consistent


def _ocr_enabled() -> bool:
    return os.getenv("OCR_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


def _read_optional_score(frame, zone: str) -> int | None:
    if not _ocr_enabled():
        return None

    try:
        from recognition.ocr_reader import read_score

        return read_score(frame, zone)
    except Exception as exc:
        logger.warning(f"OCR skipped for {zone}: {exc}")
        return None


def validate(frame, computed: dict) -> dict:
    """Enrich a computed result with OCR/rule cross-checks and confidence level."""
    computed_player_score = computed["player_value"]
    computed_banker_score = computed["banker_value"]

    ocr_player = _read_optional_score(frame, "player")
    ocr_banker = _read_optional_score(frame, "banker")

    player_match = ocr_player is not None and ocr_player == computed_player_score
    banker_match = ocr_banker is not None and ocr_banker == computed_banker_score
    ocr_available = ocr_player is not None and ocr_banker is not None
    ocr_matches = ocr_available and player_match and banker_match
    player_rules_cards = computed.get("player_cards_deal_order", computed["player_cards"])
    banker_rules_cards = computed.get("banker_cards_deal_order", computed["banker_cards"])
    rules_ok = is_rules_consistent(player_rules_cards, banker_rules_cards)
    card_count_ok = (
        2 <= computed.get("player_count", 0) <= 3
        and 2 <= computed.get("banker_count", 0) <= 3
    )

    score_source = "ocr+computed" if ocr_matches else "computed"
    validation_passed = (ocr_matches or not ocr_available) and rules_ok
    if validation_passed:
        confidence_level = "HIGH"
    elif card_count_ok and (not ocr_available or ocr_matches):
        confidence_level = "MEDIUM"
    else:
        confidence_level = "LOW"

    if confidence_level == "HIGH":
        logger.success(
            f"Validation PASSED | score P={computed_player_score} B={computed_banker_score}"
        )
    else:
        logger.warning(
            "Validation FAILED | "
            f"score P={computed_player_score} B={computed_banker_score} ({score_source}) | "
            f"OCR P={ocr_player} B={ocr_banker} | rules_ok={rules_ok}"
        )

    return {
        **computed,
        "computed_player_score": computed_player_score,
        "computed_banker_score": computed_banker_score,
        "score_player": computed_player_score,
        "score_banker": computed_banker_score,
        "score_source": score_source,
        "ocr_player_score": ocr_player,
        "ocr_banker_score": ocr_banker,
        "ocr_enabled": _ocr_enabled(),
        "ocr_available": ocr_available,
        "player_match": player_match,
        "banker_match": banker_match,
        "rules_consistent": rules_ok,
        "validation_passed": validation_passed,
        "confidence_level": confidence_level,
    }
