import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from import_export import (
    count_duplicates,
    export_to_csv,
    import_from_csv,
    import_from_json,
    load_json_import,
    merge_sets,
    rewrite_json_source,
)
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

    def test_json_import_recovers_blank_or_iso_card_dates(self):
        document = {
            "_schema_version": 3,
            "sets": {
                "import": [
                    {
                        "card_name": "Blank date",
                        "card_info": "A",
                        "card_add_info": "",
                        "card_date": "",
                    },
                    {
                        "card_name": "ISO date",
                        "card_info": "B",
                        "card_add_info": "",
                        "card_date": "2026-04-22",
                    },
                ]
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "broken_dates.sko")
            with open(path, "w") as fhand:
                json.dump(document, fhand)
            restored = import_from_json(path)
        self.assertRegex(restored["import"][0]["card_date"], r"\d{2}/\d{2}/\d{4}")
        self.assertRegex(restored["import"][1]["card_date"], r"\d{2}/\d{2}/\d{4}")

    def test_json_import_can_rewrite_recovered_source_document(self):
        document = {
            "_schema_version": 3,
            "sets": {
                "import": [
                    {
                        "card_name": "ISO date",
                        "card_info": "B",
                        "card_add_info": "",
                        "card_date": "2026-04-22",
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "recover.sko")
            with open(path, "w", encoding="utf-8") as fhand:
                json.dump(document, fhand)
            _sets, normalized_document, recovered = load_json_import(path)
            self.assertTrue(recovered)
            rewrite_json_source(path, normalized_document)
            with open(path, "r", encoding="utf-8") as fhand:
                rewritten = json.load(fhand)
        self.assertRegex(rewritten["sets"]["import"][0]["card_date"], r"\d{2}/\d{2}/\d{4}")
        self.assertNotEqual(rewritten["sets"]["import"][0]["card_date"], "2026-04-22")

    def test_merge_sets_can_replace_duplicates(self):
        existing = {"set_a": [new_card("Bonjour", "hello")]}
        incoming = {"set_a": [new_card("Bonjour", "good day"), new_card("Merci", "thanks")]}
        duplicates = count_duplicates(existing, incoming)
        merged, summary = merge_sets(existing, incoming, "replace")
        self.assertEqual(duplicates, 1)
        self.assertEqual(summary["replaced"], 1)
        self.assertEqual(summary["added"], 1)
        self.assertEqual(merged["set_a"][0]["card_info"], "good day")

    def test_csv_import_can_use_custom_field_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "mapped.csv")
            with open(path, "w", newline="") as fhand:
                writer = csv.DictWriter(fhand, fieldnames=["Topic", "Question", "Answer"])
                writer.writeheader()
                writer.writerow({"Topic": "physics", "Question": "Force", "Answer": "Mass times acceleration"})
            restored = import_from_csv(
                path,
                field_mapping={"set_name": "Topic", "card_name": "Question", "card_info": "Answer"},
            )
        self.assertEqual(restored["physics"][0]["card_name"], "Force")
        self.assertEqual(restored["physics"][0]["card_info"], "Mass times acceleration")

    def test_csv_import_recovers_invalid_numeric_boolean_and_iso_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "broken.csv")
            with open(path, "w", newline="", encoding="utf-8") as fhand:
                writer = csv.DictWriter(
                    fhand,
                    fieldnames=[
                        "set_name",
                        "card_name",
                        "card_info",
                        "card_date",
                        "suspended",
                        "ease_factor",
                        "interval",
                        "repetitions",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "set_name": "physics",
                        "card_name": "Force",
                        "card_info": "Mass times acceleration",
                        "card_date": "2026-04-22",
                        "suspended": "yes",
                        "ease_factor": "bad",
                        "interval": "x",
                        "repetitions": "y",
                    }
                )
            restored = import_from_csv(path)
        card = restored["physics"][0]
        self.assertRegex(card["card_date"], r"\d{2}/\d{2}/\d{4}")
        self.assertTrue(card["suspended"])
        self.assertEqual(card["interval"], 0)
        self.assertEqual(card["repetitions"], 0)
        self.assertEqual(card["ease_factor"], 2.5)

    def test_merge_sets_can_replace_whole_sets(self):
        existing = {"set_a": [new_card("Bonjour", "hello")], "set_b": [new_card("Merci", "thanks")]}
        incoming = {"set_a": [new_card("Salut", "hi")]}
        merged, summary = merge_sets(existing, incoming, "replace_set")
        self.assertEqual(summary["replaced_sets"], 1)
        self.assertEqual(len(merged["set_a"]), 1)
        self.assertEqual(merged["set_a"][0]["card_name"], "Salut")
        self.assertEqual(merged["set_b"][0]["card_name"], "Merci")


if __name__ == "__main__":
    unittest.main()
