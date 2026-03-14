import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import history
import storage
from schema import new_card


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_config_dir = storage.CONFIG_DIR
        storage.CONFIG_DIR = self.tmpdir.name

    def tearDown(self):
        storage.CONFIG_DIR = self.original_config_dir
        self.tmpdir.cleanup()

    def test_log_and_load_review_history(self):
        before = new_card("Front", "Back")
        after = dict(before)
        after["card_date"] = "15/03/2026"
        history.log_review_event("deck.sko", "set_a", before, after, 2, "due")
        events = history.load_history(deck_name="deck.sko", set_name="set_a", card_id=before["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["grade"], 2)
        self.assertEqual(events[0]["session_mode"], "due")
        self.assertEqual(events[0]["after"]["card_date"], "15/03/2026")


if __name__ == "__main__":
    unittest.main()
