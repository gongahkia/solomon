import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cards
import config
import history
import storage
from schema import new_card


class CardsTests(unittest.TestCase):
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

    def test_record_progress_logs_review_history(self):
        storage.write_sko("study.sko", {"set_a": [new_card("Q", "A")]}, config.load_config())
        with patch("cards.clear_screen"), patch("builtins.input", side_effect=["", "3"]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cards.main(["study", "--record-progress"]), 0)
        events = history.load_history(deck_name="study.sko", set_name="set_a")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["session_mode"], "all")
        self.assertEqual(events[0]["grade"], 2)

    def test_record_progress_undo_rewrites_history_and_card_state(self):
        first = new_card("One", "A")
        second = new_card("Two", "B")
        storage.write_sko("study.sko", {"set_a": [first, second]}, config.load_config())
        inputs = ["", "3", "", "u", "", "4", "", "3"]
        with patch("cards.clear_screen"), patch("builtins.input", side_effect=inputs):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cards.main(["study", "--record-progress"]), 0)
        events = history.load_history(deck_name="study.sko", set_name="set_a")
        self.assertEqual(len(events), 2)
        self.assertEqual([event["grade"] for event in events], [3, 2])
        saved = storage.read_sko("study.sko", config.load_config())["set_a"]
        self.assertEqual(saved[0]["easy_count"], 1)
        self.assertEqual(saved[0]["good_count"], 0)

    def test_leech_prompt_can_suspend_a_card_during_headless_review(self):
        review_card = new_card("Leech", "Back")
        review_card["state"] = "review"
        review_card["interval"] = 6
        review_card["repetitions"] = 2
        config.save_config({"srs": {"leech_threshold": 1}})
        storage.write_sko("study.sko", {"set_a": [review_card]}, config.load_config())
        with patch("cards.clear_screen"), patch("builtins.input", side_effect=["", "1", "s"]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cards.main(["study", "--record-progress"]), 0)
        saved = storage.read_sko("study.sko", config.load_config())["set_a"][0]
        self.assertTrue(saved["suspended"])

    def test_downvoted_cards_can_be_deleted_after_review(self):
        storage.write_sko("study.sko", {"set_a": [new_card("Q", "A")]}, config.load_config())
        with patch("cards.clear_screen"), patch("builtins.input", side_effect=["", "-", "3", "a"]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cards.main(["study", "--record-progress"]), 0)
        saved_cards = storage.read_sko("study.sko", config.load_config())["set_a"]
        self.assertEqual(saved_cards, [])


if __name__ == "__main__":
    unittest.main()
