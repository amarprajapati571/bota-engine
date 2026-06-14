"""Normalize outbound API/CSE payloads into one stable format."""

from __future__ import annotations

SUIT_ALIASES = {
    "C": "C",
    "CLUB": "C",
    "CLUBS": "C",
    "D": "D",
    "DIAMOND": "D",
    "DIAMONDS": "D",
    "H": "H",
    "HEART": "H",
    "HEARTS": "H",
    "S": "S",
    "SPADE": "S",
    "SPADES": "S",
}

RANK_ALIASES = {
    "1": "A",
    "A": "A",
    "ACE": "A",
    "J": "J",
    "JACK": "J",
    "Q": "Q",
    "QUEEN": "Q",
    "K": "K",
    "KING": "K",
}

CARD_KEYS = (
    "player_cards",
    "banker_cards",
    "player_cards_visual_order",
    "banker_cards_visual_order",
    "player_cards_deal_order",
    "banker_cards_deal_order",
    "playerCards",
    "bankerCards",
    "playerCardsVisualOrder",
    "bankerCardsVisualOrder",
    "playerCardsDealOrder",
    "bankerCardsDealOrder",
)


def normalize_card_code(card: object) -> str:
    """Return compact uppercase card code: AS, 10C, JH."""
    raw = str(card).strip()
    if not raw:
        return raw

    normalized = raw.replace("-", "_").replace(" ", "_").upper()
    if "_" in normalized:
        rank_raw, suit_raw = normalized.split("_", 1)
        rank = RANK_ALIASES.get(rank_raw, rank_raw)
        suit = SUIT_ALIASES.get(suit_raw, suit_raw[:1])
        return f"{rank}{suit}"

    rank_raw = normalized[:-1]
    suit_raw = normalized[-1:]
    rank = RANK_ALIASES.get(rank_raw, rank_raw)
    suit = SUIT_ALIASES.get(suit_raw, suit_raw)
    return f"{rank}{suit}"


def normalize_card_list(cards: object) -> list[str]:
    if cards is None:
        return []
    if isinstance(cards, str):
        items = [item.strip() for item in cards.split(",") if item.strip()]
    elif isinstance(cards, (list, tuple)):
        items = list(cards)
    else:
        return []
    return [normalize_card_code(item) for item in items if str(item).strip()]


def _score(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _winner(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def normalize_round_payload(result: dict, *, review_order: str = "deal") -> dict:
    """Normalize a recognition result before pushing it to an API.

    review_order="visual" makes the primary player/banker card fields match
    the screenshot left-to-right order for CSE review. Deal-order fields are
    always preserved separately.
    """
    payload = dict(result)

    for key in CARD_KEYS:
        if key in payload:
            payload[key] = normalize_card_list(payload[key])

    player_visual = normalize_card_list(
        payload.get("player_cards_visual_order") or payload.get("playerCardsVisualOrder")
    )
    banker_visual = normalize_card_list(
        payload.get("banker_cards_visual_order") or payload.get("bankerCardsVisualOrder")
    )
    player_deal = normalize_card_list(
        payload.get("player_cards_deal_order") or payload.get("player_cards")
    )
    banker_deal = normalize_card_list(
        payload.get("banker_cards_deal_order") or payload.get("banker_cards")
    )

    if review_order == "visual":
        primary_player = player_visual or player_deal
        primary_banker = banker_visual or banker_deal
        order = "visual_left_to_right"
    else:
        primary_player = player_deal
        primary_banker = banker_deal
        order = "deal_order"

    payload["player_cards"] = primary_player
    payload["banker_cards"] = primary_banker
    payload["playerCards"] = primary_player
    payload["bankerCards"] = primary_banker
    payload["player_cards_visual_order"] = player_visual
    payload["banker_cards_visual_order"] = banker_visual
    payload["playerCardsVisualOrder"] = player_visual
    payload["bankerCardsVisualOrder"] = banker_visual
    payload["player_cards_deal_order"] = player_deal
    payload["banker_cards_deal_order"] = banker_deal
    payload["playerCardsDealOrder"] = player_deal
    payload["bankerCardsDealOrder"] = banker_deal
    payload["card_order_for_review"] = order
    payload["cardOrderForReview"] = order

    winner = _winner(payload.get("final_outcome") or payload.get("outcome"))
    card_winner = _winner(payload.get("card_outcome") or payload.get("outcome"))
    payload["winner"] = winner
    payload["cardWinner"] = card_winner
    payload["playerScore"] = _score(payload.get("score_player"))
    payload["bankerScore"] = _score(payload.get("score_banker"))
    payload["computedPlayerScore"] = _score(payload.get("computed_player_score"))
    payload["computedBankerScore"] = _score(payload.get("computed_banker_score"))
    payload["confidenceLevel"] = payload.get("confidence_level")
    payload["validationPassed"] = payload.get("validation_passed")

    payload["aiPrediction"] = {
        "playerCards": primary_player,
        "bankerCards": primary_banker,
        "playerCardsVisualOrder": player_visual,
        "bankerCardsVisualOrder": banker_visual,
        "playerCardsDealOrder": player_deal,
        "bankerCardsDealOrder": banker_deal,
        "cardOrderForReview": order,
        "playerScore": payload["playerScore"],
        "bankerScore": payload["bankerScore"],
        "computedPlayerScore": payload["computedPlayerScore"],
        "computedBankerScore": payload["computedBankerScore"],
        "winner": winner,
        "cardWinner": card_winner,
        "confidenceLevel": payload.get("confidence_level"),
        "validationPassed": payload.get("validation_passed"),
    }

    return payload
