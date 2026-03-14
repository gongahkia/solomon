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


if __name__ == "__main__":
    unittest.main()
