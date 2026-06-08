"""
Baccarat scoring engine — pure Python, no ML, no I/O.

Implements standard Punto Banco rules: hand value, naturals, and the
third-card drawing rules. In the recognition pipeline the cards are *observed*
from the screen (not simulated), so the drawing-rule functions are mainly used
for sanity-checking that a recognised hand is consistent with the rules.

Card naming convention (must match your trained model's class names):

    "<rank>_<suit>"  e.g.  "A_spades", "10_hearts", "K_clubs", "5_diamonds"

    rank ∈ {A, 2, 3, 4, 5, 6, 7, 8, 9, 10, J, Q, K}   ("T" also accepted for 10)
"""
from __future__ import annotations

CARD_VALUES: dict[str, int] = {
    "A": 1, "2": 2, "3": 3, "4": 4, "5": 5,
    "6": 6, "7": 7, "8": 8, "9": 9,
    "10": 0, "J": 0, "Q": 0, "K": 0,
}


_WORD_RANKS = {
    "ACE": "A", "KING": "K", "QUEEN": "Q", "JACK": "J", "TEN": "10",
    "NINE": "9", "EIGHT": "8", "SEVEN": "7", "SIX": "6", "FIVE": "5",
    "FOUR": "4", "THREE": "3", "TWO": "2",
}


def parse_rank(card_str: str) -> str:
    """
    Extract the canonical rank from a card label, tolerant of the naming schemes
    different datasets produce:

        "A_spades", "10_hearts"   (rank_suit  — this project's convention)
        "AS", "10C", "TH", "KD"   (compact rank+suit — common on Roboflow)
        "ace of spades"           (verbose)

    Returns one of: A 2 3 4 5 6 7 8 9 10 J Q K (or the raw token if unrecognised).
    """
    s = card_str.strip().upper()
    if "_" in s:
        token = s.split("_")[0]
    elif " " in s:
        token = s.split()[0]
    elif len(s) > 1 and s[-1] in "CDHS":   # compact "AS" / "10C" / "TH"
        token = s[:-1]
    else:
        token = s
    token = _WORD_RANKS.get(token, token)
    return "10" if token == "T" else token


def card_value(card_str: str) -> int:
    """
    "5_spades" -> 5,  "K_hearts" -> 0,  "A_clubs" -> 1,
    "10_hearts" / "TH" -> 0,  "AS" -> 1,  "ace of spades" -> 1
    """
    return CARD_VALUES.get(parse_rank(card_str), 0)


def hand_value(cards: list[str]) -> int:
    """Baccarat hand value: sum of card values, modulo 10."""
    return sum(card_value(c) for c in cards) % 10


def is_natural(cards: list[str]) -> bool:
    """
    A natural is a *two-card* total of 8 or 9. A hand that has drawn a third
    card is never a natural, so this is strictly len == 2.
    """
    return len(cards) == 2 and hand_value(cards) >= 8


def player_draws_third(player_cards: list[str]) -> bool:
    """Player draws a third card on a two-card total of 0–5 (and no natural)."""
    if len(player_cards) != 2 or is_natural(player_cards):
        return False
    return hand_value(player_cards) <= 5


def banker_draws_third(banker_cards: list[str], player_cards: list[str]) -> bool:
    """
    Banker third-card rule. `banker_cards` is the banker's two-card hand;
    `player_cards` is the player's final hand (2 or 3 cards) so we can read the
    player's third-card value when the player drew.
    """
    bval = hand_value(banker_cards)
    if is_natural(banker_cards) or bval >= 7:
        return False

    # Player stood (two cards): banker simply draws on 0–5, stands on 6–7.
    if len(player_cards) == 2:
        return bval <= 5

    # Player drew a third card — banker's action depends on that card's value.
    p3 = card_value(player_cards[2])
    if bval <= 2:
        return True
    draw_when = {
        3: lambda v: v != 8,
        4: lambda v: v in (2, 3, 4, 5, 6, 7),
        5: lambda v: v in (4, 5, 6, 7),
        6: lambda v: v in (6, 7),
    }
    return draw_when[bval](p3)


def compute_result(player_cards: list[str], banker_cards: list[str]) -> dict:
    """
    Compute the final baccarat round result from the observed cards.

    Returns a plain dict; no validation or I/O happens here.
    """
    pval = hand_value(player_cards)
    bval = hand_value(banker_cards)

    if pval > bval:
        outcome = "PLAYER"
    elif bval > pval:
        outcome = "BANKER"
    else:
        outcome = "TIE"

    return {
        "player_cards": player_cards,
        "banker_cards": banker_cards,
        "player_value": pval,
        "banker_value": bval,
        "outcome": outcome,
        "is_natural": is_natural(player_cards) or is_natural(banker_cards),
        "player_count": len(player_cards),
        "banker_count": len(banker_cards),
    }


def is_rules_consistent(player_cards: list[str], banker_cards: list[str]) -> bool:
    """
    Sanity check: do the observed card counts match what the drawing rules
    require? Useful as an extra validation signal — a recognised hand that
    violates the rules almost certainly means a misread card.
    """
    if not (2 <= len(player_cards) <= 3 and 2 <= len(banker_cards) <= 3):
        return False

    p2, b2 = player_cards[:2], banker_cards[:2]
    # If either side had a natural, neither draws.
    if is_natural(p2) or is_natural(b2):
        return len(player_cards) == 2 and len(banker_cards) == 2

    player_drew = len(player_cards) == 3
    if player_drew != player_draws_third(p2):
        return False

    banker_drew = len(banker_cards) == 3
    return banker_drew == banker_draws_third(b2, player_cards)
