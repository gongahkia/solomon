import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import normalize_config


class ConfigTests(unittest.TestCase):
    def test_normalize_config_coerces_invalid_values(self):
        normalized = normalize_config(
            {
                "srs": {
                    "initial_ease": "bad",
                    "minimum_ease": 0.2,
                    "learning_steps": ["x", 2, -1],
                    "graduating_interval": "7",
                    "easy_interval": 3,
                    "max_interval": 2,
                    "leech_threshold": 0,
                },
                "tui": {
                    "show_stats": "yes",
                    "confirm_delete": "no",
                    "show_import_preview": "true",
                },
            }
        )
        self.assertEqual(normalized["srs"]["initial_ease"], 2.5)
        self.assertEqual(normalized["srs"]["minimum_ease"], 1.0)
        self.assertEqual(normalized["srs"]["learning_steps"], [2])
        self.assertEqual(normalized["srs"]["graduating_interval"], 7)
        self.assertEqual(normalized["srs"]["easy_interval"], 7)
        self.assertEqual(normalized["srs"]["max_interval"], 7)
        self.assertEqual(normalized["srs"]["leech_threshold"], 1)
        self.assertTrue(normalized["tui"]["show_stats"])
        self.assertFalse(normalized["tui"]["confirm_delete"])
        self.assertTrue(normalized["tui"]["show_import_preview"])


if __name__ == "__main__":
    unittest.main()
