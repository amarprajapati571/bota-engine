"""
Recognition pipeline: frame -> structured round result.
"""
import os
import uuid
from datetime import datetime, timezone

import numpy as np
from loguru import logger

from game_logic.baccarat_engine import (
    banker_draws_third,
    card_value,
    compute_result,
    hand_value,
    is_natural,
    is_rules_consistent,
    player_draws_third,
)
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
    if value == 0:
        return os.getenv("SCORE_ZERO_VALUE_RANK", "Q").strip().upper() or "Q"
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


def _score_card_override(zone: str, original: str, required_value: int, fallback: str) -> str:
    raw = os.getenv("SCORE_CARD_CORRECTION_OVERRIDES", "")
    if not raw:
        return fallback

    key = f"{zone}:{original}:{required_value}".upper()
    for item in raw.split(","):
        if "=" not in item:
            continue
        left, right = [part.strip() for part in item.split("=", 1)]
        if left.upper() == key and right:
            return right
    return fallback


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


def _read_display_score_for_correction(frame: np.ndarray, zone: str) -> tuple[int | None, float]:
    try:
        from recognition.score_classifier import read_score_digit, score_classifier_available

        if not score_classifier_available():
            return None, 0.0
        return read_score_digit(frame, zone)
    except Exception as exc:
        logger.debug(f"{zone} score-guided card correction skipped: {exc}")
        return None, 0.0


def _card_correction_order(cards: list[str], zone: str) -> list[int]:
    if len(cards) != 3:
        return list(range(len(cards) - 1, -1, -1))
    if zone == "player":
        return [2, 1, 0]
    # Banker middle upright card is commonly confused with a duplicate first
    # card when only the bottom corner is detected. Try it before the sideways
    # third card.
    return [1, 2, 0]


def _maybe_correct_hand_to_display_score(
    frame: np.ndarray,
    cards: list[str],
    zone: str,
) -> list[str]:
    if not _score_third_card_correction_enabled() or not (2 <= len(cards) <= 3):
        return cards

    score, score_conf = _read_display_score_for_correction(frame, zone)
    min_conf = float(os.getenv("SCORE_CARD_CORRECTION_MIN_CONF", "0.80"))
    if score is None or score_conf < min_conf or hand_value(cards) == score:
        return cards

    for index in _card_correction_order(cards, zone):
        other_value = sum(card_value(card) for i, card in enumerate(cards) if i != index) % 10
        required_value = (score - other_value) % 10
        if required_value == card_value(cards[index]):
            continue

        rank = _rank_for_value(required_value)
        if rank is None:
            continue

        corrected = list(cards)
        corrected_card = _replace_rank(corrected[index], rank)
        corrected_card = _score_card_override(zone, corrected[index], required_value, corrected_card)
        corrected[index] = corrected_card
        if hand_value(corrected) == score:
            logger.warning(
                f"Corrected {zone} card from displayed score | "
                f"{cards[index]} -> {corrected[index]} | "
                f"score={score} conf={score_conf:.3f} | cards={cards}"
            )
            return corrected

    return cards


def _maybe_trim_illegal_third_cards(
    frame: np.ndarray,
    player_cards: list[str],
    banker_cards: list[str],
) -> tuple[list[str], list[str]]:
    if os.getenv("SCORE_CARD_TRIM_ILLEGAL_THIRDS", "true").strip().lower() not in (
        "true",
        "1",
        "yes",
        "on",
    ):
        return player_cards, banker_cards

    min_conf = float(os.getenv("SCORE_CARD_CORRECTION_MIN_CONF", "0.80"))
    player_score, player_conf = _read_display_score_for_correction(frame, "player")
    banker_score, banker_conf = _read_display_score_for_correction(frame, "banker")

    trimmed_player = list(player_cards)
    trimmed_banker = list(banker_cards)

    if len(trimmed_player) == 3 and player_score is not None and player_conf >= min_conf:
        p2 = trimmed_player[:2]
        if hand_value(p2) == player_score and (is_natural(p2) or not player_draws_third(p2)):
            logger.warning(
                f"Trimmed illegal player third card | dropped={trimmed_player[2]} "
                f"| score={player_score} cards={trimmed_player}"
            )
            trimmed_player = p2

    if len(trimmed_banker) == 3 and banker_score is not None and banker_conf >= min_conf:
        b2 = trimmed_banker[:2]
        if hand_value(b2) == banker_score and (is_natural(trimmed_player[:2]) or is_natural(b2) or not banker_draws_third(b2, trimmed_player)):
            logger.warning(
                f"Trimmed illegal banker third card | dropped={trimmed_banker[2]} "
                f"| score={banker_score} cards={trimmed_banker}"
            )
            trimmed_banker = b2

    return trimmed_player, trimmed_banker


def _outcome_from_scores(player_score: int, banker_score: int) -> str:
    if player_score > banker_score:
        return "PLAYER"
    if banker_score > player_score:
        return "BANKER"
    return "TIE"


def _hand_variants_for_score(
    cards: list[str],
    zone: str,
    score: int | None,
) -> list[tuple[list[str], float, str]]:
    base_hands = [(list(cards), 0.0, "original")]
    if len(cards) == 3:
        base_hands.append((cards[:2], 0.35, "drop_third"))

    variants: list[tuple[list[str], float, str]] = []
    seen: set[tuple[str, ...]] = set()
    for hand, cost, reason in base_hands:
        key = tuple(hand)
        if key not in seen:
            seen.add(key)
            variants.append((hand, cost, reason))

        if score is None or hand_value(hand) == score:
            continue

        for index in _card_correction_order(hand, zone):
            other_value = sum(card_value(card) for i, card in enumerate(hand) if i != index) % 10
            required_value = (score - other_value) % 10
            rank = _rank_for_value(required_value)
            if rank is None:
                continue

            corrected = list(hand)
            replacement = _replace_rank(corrected[index], rank)
            replacement = _score_card_override(zone, corrected[index], required_value, replacement)
            corrected[index] = replacement
            if hand_value(corrected) != score:
                continue

            key = tuple(corrected)
            if key not in seen:
                seen.add(key)
                variants.append((
                    corrected,
                    cost + 1.0,
                    f"{reason}+rank{index}:{hand[index]}->{replacement}",
                ))

    return variants


def _maybe_reconcile_to_display_and_rules(
    frame: np.ndarray,
    player_cards: list[str],
    banker_cards: list[str],
) -> tuple[list[str], list[str]]:
    if os.getenv("SCORE_RULE_RECONCILE", "true").strip().lower() not in (
        "true",
        "1",
        "yes",
        "on",
    ):
        return player_cards, banker_cards

    min_conf = float(os.getenv("SCORE_CARD_CORRECTION_MIN_CONF", "0.80"))
    player_score, player_conf = _read_display_score_for_correction(frame, "player")
    banker_score, banker_conf = _read_display_score_for_correction(frame, "banker")
    if player_score is None or banker_score is None or player_conf < min_conf or banker_conf < min_conf:
        return player_cards, banker_cards

    try:
        from recognition.winner_badge_reader import read_winner_badge

        badge_outcome, _badge_conf = read_winner_badge(frame)
    except Exception:
        badge_outcome = None

    expected_outcome = badge_outcome or _outcome_from_scores(player_score, banker_score)

    current = compute_result(player_cards, banker_cards)
    if (
        current["player_value"] == player_score
        and current["banker_value"] == banker_score
        and current["outcome"] == expected_outcome
        and is_rules_consistent(player_cards, banker_cards)
    ):
        return player_cards, banker_cards

    best: tuple[float, list[str], list[str], str] | None = None
    player_variants = _hand_variants_for_score(player_cards, "player", player_score)
    banker_variants = _hand_variants_for_score(banker_cards, "banker", banker_score)
    for p_hand, p_cost, p_reason in player_variants:
        for b_hand, b_cost, b_reason in banker_variants:
            if not (2 <= len(p_hand) <= 3 and 2 <= len(b_hand) <= 3):
                continue
            if hand_value(p_hand) != player_score or hand_value(b_hand) != banker_score:
                continue
            result = compute_result(p_hand, b_hand)
            if result["outcome"] != expected_outcome:
                continue
            if not is_rules_consistent(p_hand, b_hand):
                continue
            cost = p_cost + b_cost
            # Prefer fewer cards only when it costs the same; this helps remove
            # spurious third-card detections on natural/stand hands.
            cost += (len(p_hand) + len(b_hand)) * 0.01
            if best is None or cost < best[0]:
                best = (cost, p_hand, b_hand, f"player={p_reason} banker={b_reason}")

    if best is None:
        return player_cards, banker_cards

    _cost, reconciled_player, reconciled_banker, reason = best
    if reconciled_player != player_cards or reconciled_banker != banker_cards:
        logger.warning(
            "Reconciled cards with display score + rules | "
            f"P {player_cards}->{reconciled_player} B {banker_cards}->{reconciled_banker} | "
            f"score={player_score}/{banker_score} outcome={expected_outcome} | {reason}"
        )
    return reconciled_player, reconciled_banker


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
    player_cards = _maybe_correct_hand_to_display_score(frame, player_cards, "player")
    banker_cards = _maybe_correct_hand_to_display_score(frame, banker_cards, "banker")
    player_cards, banker_cards = _maybe_trim_illegal_third_cards(frame, player_cards, banker_cards)
    player_cards, banker_cards = _maybe_reconcile_to_display_and_rules(frame, player_cards, banker_cards)

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
        f"({validated['score_source']}) -> {validated.get('final_outcome', result['outcome'])} | "
        f"valid={validated['validation_passed']} ({validated['confidence_level']})"
    )
    if _require_validation_passed() and not validated["validation_passed"]:
        logger.warning(f"Skipping unvalidated round | id={round_id}")
        return None
    return validated
