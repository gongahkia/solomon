import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import history
import storage
from review_session import apply_review, review_summary_lines, start_session, undo_last_review
from schema import new_card


class ReviewSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_config_path = config.CONFIG_PATH
        self.original_storage_dir = storage.CONFIG_DIR
        config.CONFIG_PATH = os.path.join(self.tmpdir.name, "config.json")
        storage.CONFIG_DIR = os.path.join(self.tmpdir.name, "decks")

    def tearDown(self):
        config.CONFIG_PATH = self.original_config_path
        storage.CONFIG_DIR = self.original_storage_dir
        self.tmpdir.cleanup()

    def test_apply_review_logs_history_and_updates_counts(self):
        card = new_card("Q", "A")
        session = start_session([card], "all")
        apply_review(
            session,
            deck_name="study.sko",
            set_name="set_a",
            card=card,
            grade=2,
            config=config.load_config(),
        )
        self.assertEqual(session["counts"][2], 1)
        self.assertEqual(len(session["history"]), 1)
        self.assertEqual(len(history.load_history(deck_name="study.sko", set_name="set_a")), 1)

    def test_undo_last_review_restores_card_and_removes_logged_event(self):
        card = new_card("Q", "A")
        original_date = card["card_date"]
        session = start_session([card], "all")
        apply_review(
            session,
            deck_name="study.sko",
            set_name="set_a",
            card=card,
            grade=3,
            config=config.load_config(),
        )
        removed = undo_last_review(session, deck_name="study.sko", set_name="set_a")
        self.assertIsNotNone(removed)
        self.assertEqual(card["card_date"], original_date)
        self.assertEqual(session["counts"][3], 0)
        self.assertEqual(history.load_history(deck_name="study.sko", set_name="set_a"), [])

    def test_review_summary_lines_reflect_counts(self):
        card = new_card("Q", "A")
        session = start_session([card], "all")
        apply_review(
            session,
            deck_name="study.sko",
            set_name="set_a",
            card=card,
            grade=1,
            config=config.load_config(),
        )
        lines = review_summary_lines(session, [card])
        self.assertIn("Reviewed 1 cards", lines[0])
        self.assertIn("Hard 1", lines[1])


if __name__ == "__main__":
    unittest.main()
