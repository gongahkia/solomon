import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from import_export import count_duplicates, export_to_csv, export_to_json, import_from_csv, import_from_json, merge_sets
from schema import new_card


class ImportExportTests(unittest.TestCase):
    def test_csv_round_trip_preserves_cards(self):
        deck = {
            "biology": [
                new_card("Cell", "Basic unit", tags=["science", "bio"]),
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "deck.csv")
            export_to_csv(deck, path)
            restored = import_from_csv(path)
        self.assertEqual(restored["biology"][0]["card_name"], "Cell")
        self.assertEqual(restored["biology"][0]["tags"], ["science", "bio"])

    def test_json_import_accepts_versioned_documents(self):
        document = {
            "_schema_version": 2,
            "sets": {
                "chemistry": [
                    {
                        "card_name": "Atom",
                        "card_info": "Matter",
                        "card_add_info": "",
                        "card_date": "14/03/2026",
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "deck.json")
            with open(path, "w") as fhand:
                json.dump(document, fhand)
            restored = import_from_json(path)
        self.assertIn("chemistry", restored)
        self.assertEqual(restored["chemistry"][0]["card_name"], "Atom")

    def test_merge_sets_can_replace_duplicates(self):
        existing = {"set_a": [new_card("Bonjour", "hello")]}
        incoming = {"set_a": [new_card("Bonjour", "good day"), new_card("Merci", "thanks")]}
        duplicates = count_duplicates(existing, incoming)
        merged, summary = merge_sets(existing, incoming, "replace")
        self.assertEqual(duplicates, 1)
        self.assertEqual(summary["replaced"], 1)
        self.assertEqual(summary["added"], 1)
        self.assertEqual(merged["set_a"][0]["card_info"], "good day")


if __name__ == "__main__":
    unittest.main()
