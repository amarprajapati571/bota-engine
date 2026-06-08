"""
Unit tests for the pure baccarat engine.

Run from the project root with either:
    python3 -m unittest tests.test_baccarat_engine -v
    python3 tests/test_baccarat_engine.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game_logic.baccarat_engine import (  # noqa: E402
    card_value,
    hand_value,
    is_natural,
    player_draws_third,
    banker_draws_third,
    compute_result,
    is_rules_consistent,
)


class TestCardValue(unittest.TestCase):
    def test_ranks(self):
        self.assertEqual(card_value("A_hearts"), 1)
        self.assertEqual(card_value("5_spades"), 5)
        self.assertEqual(card_value("9_clubs"), 9)
        self.assertEqual(card_value("10_clubs"), 0)
        self.assertEqual(card_value("J_diamonds"), 0)
        self.assertEqual(card_value("Q_hearts"), 0)
        self.assertEqual(card_value("K_spades"), 0)

    def test_ten_aliases_and_case(self):
        self.assertEqual(card_value("T_hearts"), 0)
        self.assertEqual(card_value("a_clubs"), 1)

    def test_compact_dataset_names(self):
        # Roboflow-style "rank+suit" single tokens
        self.assertEqual(card_value("AS"), 1)    # ace of spades
        self.assertEqual(card_value("10C"), 0)   # ten of clubs
        self.assertEqual(card_value("TH"), 0)    # ten of hearts
        self.assertEqual(card_value("KD"), 0)    # king of diamonds
        self.assertEqual(card_value("7H"), 7)

    def test_verbose_names(self):
        self.assertEqual(card_value("ace of spades"), 1)
        self.assertEqual(card_value("ten of clubs"), 0)
        self.assertEqual(card_value("five of hearts"), 5)


class TestHandValue(unittest.TestCase):
    def test_mod_ten(self):
        self.assertEqual(hand_value(["9_h", "7_s"]), 6)   # 16 -> 6
        self.assertEqual(hand_value(["5_s", "5_d"]), 0)   # 10 -> 0
        self.assertEqual(hand_value(["K_h", "10_s"]), 0)
        self.assertEqual(hand_value(["A_c", "2_d", "3_h"]), 6)


class TestNatural(unittest.TestCase):
    def test_two_card_naturals(self):
        self.assertTrue(is_natural(["8_h", "A_s"]))       # 9
        self.assertTrue(is_natural(["9_h", "K_s"]))       # 9
        self.assertTrue(is_natural(["5_h", "3_s"]))       # 8

    def test_not_natural(self):
        # 8 + 9 = 17 -> 7, a total of 7 is NOT a natural
        self.assertFalse(is_natural(["8_h", "9_s"]))
        # three cards can never be a natural even if first two summed to 8
        self.assertFalse(is_natural(["5_h", "3_s", "2_d"]))


class TestPlayerDraw(unittest.TestCase):
    def test_draws_on_0_to_5(self):
        self.assertTrue(player_draws_third(["2_h", "3_s"]))   # 5
        self.assertTrue(player_draws_third(["4_h", "A_s"]))   # 5
        self.assertTrue(player_draws_third(["K_h", "Q_s"]))   # 0

    def test_stands_on_6_7_and_naturals(self):
        self.assertFalse(player_draws_third(["6_h", "K_s"]))  # 6
        self.assertFalse(player_draws_third(["5_h", "A_s"]))  # 6
        self.assertFalse(player_draws_third(["8_h", "A_s"]))  # 9 natural


class TestBankerDraw(unittest.TestCase):
    def test_banker_natural_or_high_stands(self):
        self.assertFalse(banker_draws_third(["9_h", "K_s"], ["2_h", "3_s"]))  # natural
        self.assertFalse(banker_draws_third(["7_h", "K_s"], ["2_h", "3_s"]))  # 7

    def test_player_stood(self):
        # player stood with 2 cards -> banker draws 0-5, stands 6-7
        self.assertTrue(banker_draws_third(["3_c", "2_d"], ["6_h", "K_s"]))   # b=5
        self.assertFalse(banker_draws_third(["6_c", "K_d"], ["6_h", "K_s"]))  # b=6

    def test_player_drew_third_card_rules(self):
        # banker 0-2 always draws
        self.assertTrue(banker_draws_third(["A_c", "A_d"], ["2_h", "3_s", "9_d"]))  # b=2
        # banker 3: stands only when player's 3rd card is an 8
        self.assertFalse(banker_draws_third(["A_c", "2_d"], ["2_h", "3_s", "8_d"]))  # p3=8
        self.assertTrue(banker_draws_third(["A_c", "2_d"], ["2_h", "3_s", "7_d"]))   # p3=7
        # banker 6: draws only on player 3rd card 6 or 7
        self.assertTrue(banker_draws_third(["3_c", "3_d"], ["2_h", "3_s", "6_d"]))   # p3=6
        self.assertFalse(banker_draws_third(["3_c", "3_d"], ["2_h", "3_s", "5_d"]))  # p3=5


class TestComputeResult(unittest.TestCase):
    def test_tie_with_naturals(self):
        r = compute_result(["9_h", "K_s"], ["7_c", "2_d"])  # 9 vs 9
        self.assertEqual(r["outcome"], "TIE")
        self.assertTrue(r["is_natural"])

    def test_banker_wins(self):
        r = compute_result(["5_h", "3_s"], ["K_c", "9_d"])  # 8 vs 9
        self.assertEqual(r["outcome"], "BANKER")
        self.assertTrue(r["is_natural"])

    def test_player_wins_with_third_cards(self):
        r = compute_result(["2_h", "3_s", "4_d"], ["5_c", "5_d", "K_h"])  # 9 vs 0
        self.assertEqual(r["outcome"], "PLAYER")
        self.assertEqual(r["player_count"], 3)
        self.assertEqual(r["banker_count"], 3)
        self.assertFalse(r["is_natural"])


class TestRulesConsistency(unittest.TestCase):
    def test_consistent_hands(self):
        # natural -> nobody draws
        self.assertTrue(is_rules_consistent(["9_h", "K_s"], ["2_c", "5_d"]))
        # player draws (5), banker total 5 draws because player's 3rd card is 5 (in 4-7)
        self.assertTrue(is_rules_consistent(["2_h", "3_s", "5_d"], ["3_c", "2_d", "K_h"]))

    def test_inconsistent_hand(self):
        # player total 6 should stand, so a 3-card player hand here is impossible
        self.assertFalse(is_rules_consistent(["6_h", "K_s", "2_d"], ["3_c", "2_d"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
