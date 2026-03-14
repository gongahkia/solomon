import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from schema import DOCUMENT_SETS_KEY, DOCUMENT_VERSION_KEY, SCHEMA_VERSION, SchemaError, normalize_document, reset_card_progress


class SchemaTests(unittest.TestCase):
    def test_normalize_legacy_document_adds_v2_metadata(self):
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


if __name__ == "__main__":
    unittest.main()
