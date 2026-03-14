import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cli
import config
import history
import storage


class CLITests(unittest.TestCase):
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

    def test_import_validate_and_export_workflow(self):
        source = os.path.join(self.tmpdir.name, "source.txt")
        with open(source, "w") as fhand:
            fhand.write("---\nTOPIC: science\nAtom\nSmallest unit of matter\n---\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run_cli(["import", source, "study_deck"]), 0)
            self.assertEqual(cli.run_cli(["validate"]), 0)
            export_path = os.path.join(self.tmpdir.name, "deck.json")
            self.assertEqual(cli.run_cli(["export", "study_deck", "--format", "json", "--output", export_path]), 0)
        self.assertTrue(os.path.exists(export_path))

    def test_migrate_rewrites_legacy_document(self):
        legacy_path = os.path.join(self.tmpdir.name, "legacy.json")
        migrated_path = os.path.join(self.tmpdir.name, "migrated.json")
        with open(legacy_path, "w") as fhand:
            json.dump(
                {
                    "history": [
                        {
                            "card_name": "Year",
                            "card_info": "1066",
                            "card_add_info": "Norman conquest",
                            "card_date": "14/03/2026",
                        }
                    ]
                },
                fhand,
            )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run_cli(["migrate", legacy_path, "--output", migrated_path]), 0)
        with open(migrated_path, "r") as fhand:
            document = json.load(fhand)
        self.assertEqual(document["_schema_version"], 3)
        self.assertIn("sets", document)

    def test_cli_can_manage_cards_and_print_stats(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.run_cli(["create-deck", "study"]), 0)
            self.assertEqual(cli.run_cli(["create-set", "study", "set_a"]), 0)
            self.assertEqual(
                cli.run_cli(
                    [
                        "add-card",
                        "study",
                        "set_a",
                        "--name",
                        "Bonjour",
                        "--info",
                        "hello",
                        "--tags",
                        "french,greeting",
                    ]
                ),
                0,
            )
            self.assertEqual(cli.run_cli(["create-set", "study", "set_b"]), 0)
            self.assertEqual(cli.run_cli(["move-card", "study", "set_a", "set_b", "Bonjour"]), 0)
            self.assertEqual(cli.run_cli(["suspend-card", "study", "set_b", "Bonjour"]), 0)
            self.assertEqual(cli.run_cli(["reset-card", "study", "set_b", "Bonjour"]), 0)
            self.assertEqual(cli.run_cli(["stats", "--deck", "study"]), 0)
        stdout = output.getvalue()
        self.assertIn("Created deck study.sko", stdout)
        self.assertIn("Moved Bonjour to set_b", stdout)
        self.assertIn("Suspended Bonjour", stdout)
        self.assertIn("[Overview]", stdout)
        cards_output = io.StringIO()
        with redirect_stdout(cards_output):
            self.assertEqual(cli.run_cli(["list-cards", "study", "--set", "set_b"]), 0)
        self.assertIn("Bonjour", cards_output.getvalue())

    def test_cli_supports_edit_duplicate_reorder_and_delete_workflows(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run_cli(["create-deck", "study"]), 0)
            self.assertEqual(cli.run_cli(["create-set", "study", "alpha"]), 0)
            self.assertEqual(cli.run_cli(["add-card", "study", "alpha", "--name", "Hello", "--info", "World"]), 0)
            self.assertEqual(
                cli.run_cli(
                    [
                        "edit-card",
                        "study",
                        "alpha",
                        "Hello",
                        "--notes",
                        "Greeting card",
                        "--tags",
                        "english,common",
                    ]
                ),
                0,
            )
            self.assertEqual(cli.run_cli(["duplicate-card", "study", "alpha", "Hello"]), 0)
            self.assertEqual(cli.run_cli(["reorder-card", "study", "alpha", "Hello (copy)", "up"]), 0)
            self.assertEqual(cli.run_cli(["create-set", "study", "beta"]), 0)
            self.assertEqual(cli.run_cli(["move-card", "study", "alpha", "beta", "Hello (copy)"]), 0)
            self.assertEqual(cli.run_cli(["rename-set", "study", "beta", "gamma"]), 0)
            self.assertEqual(cli.run_cli(["delete-card", "study", "gamma", "Hello (copy)"]), 0)
            self.assertEqual(cli.run_cli(["delete-set", "study", "gamma"]), 0)
        deck = storage.read_sko("study.sko", config.load_config())
        self.assertIn("alpha", deck)
        self.assertNotIn("gamma", deck)
        self.assertEqual(len(deck["alpha"]), 1)
        self.assertEqual(deck["alpha"][0]["card_add_info"], "Greeting card")
        self.assertEqual(deck["alpha"][0]["tags"], ["english", "common"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run_cli(["delete-deck", "study", "--force"]), 0)
        self.assertFalse(os.path.exists(storage.sko_path("study.sko")))

    def test_cli_can_review_and_manage_history(self):
        history_export = os.path.join(self.tmpdir.name, "history.json")
        history_archive = os.path.join(self.tmpdir.name, "history.jsonl")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run_cli(["create-deck", "study"]), 0)
            self.assertEqual(cli.run_cli(["create-set", "study", "alpha"]), 0)
            self.assertEqual(cli.run_cli(["add-card", "study", "alpha", "--name", "Hello", "--info", "World"]), 0)
        with patch("cards.clear_screen"), patch("builtins.input", side_effect=["", "3"]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.run_cli(["review", "study", "--record-progress"]), 0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run_cli(["export-history", history_export, "--deck", "study", "--format", "json"]), 0)
        with open(history_export, "r", encoding="utf-8") as fhand:
            exported = json.load(fhand)
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["deck_name"], "study.sko")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.run_cli(["archive-history", history_archive, "--deck", "study"]), 0)
        self.assertEqual(history.load_history(deck_name="study.sko"), [])
        with open(history.history_path(), "a", encoding="utf-8") as fhand:
            fhand.write("{bad json}\n")
        rebuild_output = io.StringIO()
        with redirect_stdout(rebuild_output):
            self.assertEqual(cli.run_cli(["rebuild-history"]), 0)
        self.assertIn("dropped 1 invalid lines", rebuild_output.getvalue())


if __name__ == "__main__":
    unittest.main()
