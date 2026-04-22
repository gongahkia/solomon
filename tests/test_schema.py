import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from schema import (
    DOCUMENT_SETS_KEY,
    DOCUMENT_VERSION_KEY,
    SCHEMA_VERSION,
    SchemaError,
    normalize_document,
    reset_card_progress,
)


class SchemaTests(unittest.TestCase):
    def test_normalize_legacy_document_adds_current_metadata(self):
        legacy = {
            "japanese": [
                {
                    "card_name": "なる",
                    "card_info": "na ru",
                    "card_add_info": "become",
                    "card_date": "14/03/2026",
                }
            ]
        }
        document = normalize_document(legacy, {"srs": {"initial_ease": 1.9}})
        self.assertEqual(document[DOCUMENT_VERSION_KEY], SCHEMA_VERSION)
        card = document[DOCUMENT_SETS_KEY]["japanese"][0]
        self.assertEqual(card["ease_factor"], 1.9)
        self.assertIn("id", card)
        self.assertIn("created_at", card)
        self.assertEqual(card["tags"], [])
        self.assertFalse(card["suspended"])
        self.assertEqual(card["state"], "new")
        self.assertEqual(card["lapses"], 0)
        self.assertEqual(card["good_count"], 0)

    def test_normalize_document_rejects_blank_card_names(self):
        with self.assertRaises(SchemaError):
            normalize_document(
                {
                    "broken": [
                        {
                            "card_name": " ",
                            "card_info": "",
                            "card_add_info": "",
                            "card_date": "14/03/2026",
                        }
                    ]
                }
            )

    def test_reset_card_progress_uses_config_initial_ease(self):
        document = normalize_document(
            {
                "deck": [
                    {
                        "card_name": "Q",
                        "card_info": "A",
                        "card_add_info": "",
                        "card_date": "14/03/2026",
                    }
                ]
            }
        )
        card = document[DOCUMENT_SETS_KEY]["deck"][0]
        card["ease_factor"] = 3.1
        card["interval"] = 10
        card["repetitions"] = 4
        reset_card_progress(card, {"srs": {"initial_ease": 2.1}})
        self.assertEqual(card["ease_factor"], 2.1)
        self.assertEqual(card["interval"], 0)
        self.assertEqual(card["repetitions"], 0)
        self.assertEqual(card["state"], "new")
        self.assertEqual(card["step_index"], 0)

    def test_normalize_document_recovers_invalid_card_dates_and_types(self):
        document = normalize_document(
            {
                "import": [
                    {
                        "card_name": "Q1",
                        "card_info": "A1",
                        "card_add_info": "",
                        "card_date": "",
                        "suspended": "true",
                        "interval": "4",
                        "repetitions": "2",
                        "ease_factor": "2.8",
                    },
                    {
                        "card_name": "Q2",
                        "card_info": "A2",
                        "card_add_info": "",
                        "card_date": "2026-04-22",
                    },
                ]
            }
        )
        first = document[DOCUMENT_SETS_KEY]["import"][0]
        second = document[DOCUMENT_SETS_KEY]["import"][1]
        self.assertTrue(first["suspended"])
        self.assertEqual(first["interval"], 4)
        self.assertEqual(first["repetitions"], 2)
        self.assertEqual(first["ease_factor"], 2.8)
        self.assertRegex(first["card_date"], r"\d{2}/\d{2}/\d{4}")
        self.assertRegex(second["card_date"], r"\d{2}/\d{2}/\d{4}")
        self.assertNotEqual(second["card_date"], "2026-04-22")


if __name__ == "__main__":
    unittest.main()
