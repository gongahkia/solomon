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

    def test_export_archive_prune_and_rebuild_history(self):
        first_before = new_card("Front", "Back")
        first_after = dict(first_before)
        first_after["card_date"] = "15/03/2026"
        second_before = new_card("Hola", "Hello")
        second_after = dict(second_before)
        second_after["card_date"] = "16/03/2026"
        history.log_review_event("deck.sko", "set_a", first_before, first_after, 2, "due")
        history.log_review_event("other.sko", "set_b", second_before, second_after, 1, "all")

        export_path = os.path.join(self.tmpdir.name, "deck-history.json")
        export_result = history.export_history(export_path, deck_name="deck.sko", format="json")
        self.assertEqual(export_result["exported"], 1)
        self.assertTrue(os.path.exists(export_path))

        archive_path = os.path.join(self.tmpdir.name, "archive.jsonl")
        archive_result = history.archive_history(archive_path, deck_name="deck.sko")
        self.assertEqual(archive_result["archived"], 1)
        self.assertEqual(len(history.load_history(deck_name="deck.sko")), 0)
        self.assertEqual(len(history.load_history(deck_name="other.sko")), 1)

        prune_result = history.prune_history(deck_name="other.sko")
        self.assertEqual(prune_result["removed"], 1)
        self.assertEqual(history.load_history(), [])

        with open(history.history_path(), "a", encoding="utf-8") as fhand:
            fhand.write("{not-json}\n")
        rebuild_result = history.rebuild_history()
        self.assertEqual(rebuild_result["events"], 0)
        self.assertEqual(rebuild_result["dropped_lines"], 1)

    def test_pop_last_review_event_removes_only_the_latest_matching_event(self):
        first_before = new_card("Front", "Back")
        first_after = dict(first_before)
        first_after["card_date"] = "15/03/2026"
        second_before = new_card("Front", "Back again")
        second_after = dict(second_before)
        second_after["card_date"] = "16/03/2026"
        history.log_review_event("deck.sko", "set_a", first_before, first_after, 2, "due")
        history.log_review_event("deck.sko", "set_a", second_before, second_after, 1, "due")
        removed = history.pop_last_review_event(deck_name="deck.sko", set_name="set_a", card_id=second_before["id"])
        self.assertEqual(removed["after"]["card_id"], second_before["id"])
        remaining = history.load_history(deck_name="deck.sko", set_name="set_a")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["after"]["card_id"], first_before["id"])


if __name__ == "__main__":
    unittest.main()
