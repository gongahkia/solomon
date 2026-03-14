import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import storage
from schema import new_card


class StorageTests(unittest.TestCase):
    def test_write_and_read_sko_round_trip(self):
        original_dir = storage.CONFIG_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            storage.CONFIG_DIR = tmpdir
            storage.write_sko("deck.sko", {"set_a": [new_card("Front", "Back")]})
            restored = storage.read_sko("deck.sko")
            self.assertEqual(restored["set_a"][0]["card_name"], "Front")
        storage.CONFIG_DIR = original_dir

    def test_inspect_sko_reports_invalid_files(self):
        original_dir = storage.CONFIG_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            storage.CONFIG_DIR = tmpdir
            path = storage.sko_path("broken.sko")
            with open(path, "w") as fhand:
                json.dump({"set_a": [{"card_name": ""}]}, fhand)
            status = storage.inspect_sko("broken.sko")
            self.assertFalse(status["valid"])
            self.assertTrue(status["error"])
        storage.CONFIG_DIR = original_dir


if __name__ == "__main__":
    unittest.main()
