import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from schema import new_card
from srs import cards_due, cards_due_count, sm2_review


class SRSTests(unittest.TestCase):
    def test_hard_review_uses_configured_hard_factor(self):
        card = new_card("Front", "Back", config={"srs": {"initial_ease": 2.7}})
        card["interval"] = 10
        card["repetitions"] = 3
        card["state"] = "review"
        sm2_review(card, 1, {"srs": {"minimum_ease": 1.3, "hard_factor": 0.5}})
        self.assertEqual(card["interval"], 5)
        self.assertEqual(card["repetitions"], 4)

    def test_suspended_cards_are_not_due_by_default(self):
        due_card = new_card("Due", "Answer")
        due_card["suspended"] = True
        cards = [due_card]
        self.assertEqual(cards_due(cards), [])
        self.assertEqual(cards_due_count(cards), 0)
        self.assertEqual(len(cards_due(cards, include_suspended=True)), 1)

    def test_easy_review_grows_interval(self):
        card = new_card("Front", "Back")
        card["interval"] = 6
        card["repetitions"] = 2
        card["state"] = "review"
        sm2_review(card, 3, {"srs": {"easy_bonus": 1.5}})
        self.assertGreater(card["interval"], 6)
        self.assertEqual(card["repetitions"], 3)

    def test_again_from_review_enters_relearning_and_counts_lapse(self):
        card = new_card("Front", "Back")
        card["interval"] = 12
        card["repetitions"] = 4
        card["state"] = "review"
        sm2_review(card, 0, {"srs": {"relearning_steps": [2, 4]}})
        self.assertEqual(card["state"], "relearning")
        self.assertEqual(card["interval"], 2)
        self.assertEqual(card["lapses"], 1)

    def test_interval_is_capped_by_configured_max_interval(self):
        card = new_card("Front", "Back")
        card["interval"] = 100
        card["repetitions"] = 5
        card["state"] = "review"
        sm2_review(card, 3, {"srs": {"max_interval": 30}})
        self.assertEqual(card["interval"], 30)


if __name__ == "__main__":
    unittest.main()
