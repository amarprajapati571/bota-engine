"""
Cross-validation layer.
"""
import os

from loguru import logger

from game_logic.baccarat_engine import is_rules_consistent


def _ocr_enabled() -> bool:
    return os.getenv("OCR_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


def _score_classifier_enabled() -> bool:
    return os.getenv("SCORE_CLASSIFIER_ENABLED", "true").strip().lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


def _read_score_classifier(frame, zone: str) -> tuple[int | None, float]:
    if not _score_classifier_enabled():
        return None, 0.0

    try:
        from recognition.score_classifier import read_score_digit, score_classifier_available

        if not score_classifier_available():
            return None, 0.0
        score, conf = read_score_digit(frame, zone)
        min_conf = float(os.getenv("SCORE_CLASSIFIER_MIN_CONF", "0.80"))
        if score is not None and conf >= min_conf:
            return score, conf
        return None, conf
    except Exception as exc:
        logger.warning(f"Score classifier skipped for {zone}: {exc}")
        return None, 0.0


def _read_ocr_score(frame, zone: str) -> int | None:
    if not _ocr_enabled():
        return None
    try:
        from recognition.ocr_reader import read_score

        return read_score(frame, zone)
    except Exception as exc:
        logger.warning(f"OCR skipped for {zone}: {exc}")
        return None


def _read_optional_score(frame, zone: str) -> dict:
    cls_score, cls_conf = _read_score_classifier(frame, zone)
    ocr_score = None
    if cls_score is None:
        ocr_score = _read_ocr_score(frame, zone)

    if cls_score is not None:
        display_score = cls_score
        source = "classifier"
        confidence = cls_conf
    elif ocr_score is not None:
        display_score = ocr_score
        source = "ocr"
        confidence = None
    else:
        display_score = None
        source = None
        confidence = cls_conf if cls_conf else None

    return {
        "display": display_score,
        "source": source,
        "classifier": cls_score,
        "classifier_confidence": round(cls_conf, 4) if cls_conf else None,
        "ocr": ocr_score,
        "confidence": round(confidence, 4) if confidence is not None else None,
    }


def _read_optional_winner_badge(frame) -> tuple[str | None, float]:
    try:
        from recognition.winner_badge_reader import read_winner_badge

        return read_winner_badge(frame)
    except Exception as exc:
        logger.warning(f"Winner badge read skipped: {exc}")
        return None, 0.0


def _outcome_from_scores(player_score: int, banker_score: int) -> str:
    if player_score > banker_score:
        return "PLAYER"
    if banker_score > player_score:
        return "BANKER"
    return "TIE"


def _trust_display_score_badge() -> bool:
    return os.getenv("TRUST_DISPLAY_SCORE_BADGE", "false").strip().lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


def _ignore_baccarat_rules() -> bool:
    return os.getenv("VALIDATION_IGNORE_BACCARAT_RULES", "true").strip().lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


def validate(frame, computed: dict) -> dict:
    """Enrich a computed result with OCR/rule cross-checks and confidence level."""
    computed_player_score = computed["player_value"]
    computed_banker_score = computed["banker_value"]

    player_score_read = _read_optional_score(frame, "player")
    banker_score_read = _read_optional_score(frame, "banker")
    display_player = player_score_read["display"]
    display_banker = banker_score_read["display"]
    ocr_player = player_score_read["ocr"]
    ocr_banker = banker_score_read["ocr"]
    badge_outcome, badge_conf = _read_optional_winner_badge(frame)

    player_match = display_player is not None and display_player == computed_player_score
    banker_match = display_banker is not None and display_banker == computed_banker_score
    display_scores_available = display_player is not None and display_banker is not None
    display_scores_match = display_scores_available and player_match and banker_match
    ocr_available = ocr_player is not None and ocr_banker is not None
    badge_available = badge_outcome is not None
    badge_match = badge_available and badge_outcome == computed.get("outcome")
    player_rules_cards = computed.get("player_cards_deal_order", computed["player_cards"])
    banker_rules_cards = computed.get("banker_cards_deal_order", computed["banker_cards"])
    rules_ok = is_rules_consistent(player_rules_cards, banker_rules_cards)
    rules_gate_ok = rules_ok or _ignore_baccarat_rules()
    card_count_ok = (
        2 <= computed.get("player_count", 0) <= 3
        and 2 <= computed.get("banker_count", 0) <= 3
    )

    if display_scores_available:
        display_sources = {
            player_score_read["source"],
            banker_score_read["source"],
        }
        display_sources.discard(None)
        score_source = "+".join(sorted(display_sources)) or "display"
    elif display_player is not None or display_banker is not None:
        score_source = "partial_display+computed"
    else:
        score_source = "computed"

    score_player = display_player if display_player is not None else computed_player_score
    score_banker = display_banker if display_banker is not None else computed_banker_score
    final_outcome = badge_outcome if badge_available else computed.get("outcome")
    display_outcome = (
        _outcome_from_scores(display_player, display_banker)
        if display_scores_available
        else None
    )
    display_badge_agree = (
        display_scores_available
        and badge_available
        and badge_outcome == display_outcome
    )
    score_outcome = _outcome_from_scores(score_player, score_banker)
    score_badge_agree = badge_available and badge_outcome == score_outcome
    validation_passed = (
        (display_scores_match or not display_scores_available)
        and (badge_match or not badge_available)
        and rules_gate_ok
    )
    trusted_display_pass = (
        _trust_display_score_badge()
        and score_source != "computed"
        and score_badge_agree
    )
    if trusted_display_pass:
        validation_passed = True

    if validation_passed and trusted_display_pass:
        confidence_level = "HIGH"
    elif validation_passed:
        confidence_level = "HIGH"
    elif (not rules_gate_ok) or (badge_available and not badge_match):
        confidence_level = "LOW"
    elif card_count_ok and (not display_scores_available or display_scores_match):
        confidence_level = "MEDIUM"
    else:
        confidence_level = "LOW"

    if confidence_level == "HIGH":
        logger.success(
            f"Validation PASSED | score P={score_player} B={score_banker} | "
            f"outcome={final_outcome}"
        )
    else:
        logger.warning(
            "Validation FAILED | "
            f"score P={score_player} B={score_banker} ({score_source}) | "
            f"computed P={computed_player_score} B={computed_banker_score} | "
            f"display P={display_player} B={display_banker} | OCR P={ocr_player} B={ocr_banker} | "
            f"badge={badge_outcome} computed_outcome={computed.get('outcome')} | "
            f"rules_ok={rules_ok} ignored={_ignore_baccarat_rules()}"
        )

    return {
        **computed,
        "computed_player_score": computed_player_score,
        "computed_banker_score": computed_banker_score,
        "card_outcome": computed.get("outcome"),
        "final_outcome": final_outcome,
        "score_player": score_player,
        "score_banker": score_banker,
        "score_source": score_source,
        "ocr_player_score": ocr_player,
        "ocr_banker_score": ocr_banker,
        "ocr_enabled": _ocr_enabled(),
        "ocr_available": ocr_available,
        "display_player_score": display_player,
        "display_banker_score": display_banker,
        "display_score_available": display_scores_available,
        "display_outcome": display_outcome,
        "display_badge_agree": display_badge_agree,
        "score_outcome": score_outcome,
        "score_badge_agree": score_badge_agree,
        "trusted_display_badge": trusted_display_pass,
        "display_score_source_player": player_score_read["source"],
        "display_score_source_banker": banker_score_read["source"],
        "score_classifier_player_score": player_score_read["classifier"],
        "score_classifier_banker_score": banker_score_read["classifier"],
        "score_classifier_player_conf": player_score_read["classifier_confidence"],
        "score_classifier_banker_conf": banker_score_read["classifier_confidence"],
        "winner_badge_outcome": badge_outcome,
        "winner_badge_confidence": badge_conf,
        "winner_badge_available": badge_available,
        "winner_badge_match": badge_match,
        "player_match": player_match,
        "banker_match": banker_match,
        "rules_consistent": rules_ok,
        "rules_ignored": _ignore_baccarat_rules(),
        "validation_passed": validation_passed,
        "confidence_level": confidence_level,
    }
