import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import deck_screens
import storage
from schema import new_card


class FakeScreen:
    def __init__(self, keys=None):
        self.keys = list(keys or [])

    def erase(self):
        return None

    def getmaxyx(self):
        return (24, 80)

    def addstr(self, y, x, text, attr=0):
        return None

    def refresh(self):
        return None

    def getch(self):
        if self.keys:
            return self.keys.pop(0)
        return ord("q")


class DeckScreenTests(unittest.TestCase):
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

    def test_select_sko_file_can_create_and_select_a_deck(self):
        screen = FakeScreen()
        with patch("deck_screens.select_from_list", side_effect=[(None, "n"), 0]), patch(
            "deck_screens.text_input", return_value="study"
        ):
            selected = deck_screens.select_sko_file(screen, config.load_config())
        self.assertEqual(selected, "study.sko")
        self.assertTrue(os.path.exists(storage.sko_path("study.sko")))

    def test_select_flashcard_set_can_rename_and_return_the_new_set(self):
        storage.write_sko("study.sko", {"old_set": []}, config.load_config())
        screen = FakeScreen()
        with patch("deck_screens.select_from_list", side_effect=[(0, "r"), 0]), patch(
            "deck_screens.text_input", return_value="new_set"
        ):
            selected = deck_screens.select_flashcard_set(
                screen,
                storage.read_sko("study.sko", config.load_config()),
                "study.sko",
                config.load_config(),
            )
        self.assertEqual(selected[0], "new_set")
        self.assertIn("new_set", storage.read_sko("study.sko", config.load_config()))

    def test_config_editor_toggles_and_persists_boolean_settings(self):
        screen = FakeScreen()
        with patch("deck_screens.select_from_list", side_effect=[10, None]):
            updated = deck_screens.config_editor(screen, config.load_config())
        self.assertFalse(updated["tui"]["show_stats"])
        self.assertFalse(config.load_config()["tui"]["show_stats"])

    def test_csv_mapping_screen_can_accept_the_inferred_mapping(self):
        csv_path = os.path.join(self.tmpdir.name, "cards.csv")
        with open(csv_path, "w", encoding="utf-8") as fhand:
            fhand.write("set_name,card_name,card_info\nalpha,Hello,World\n")
        screen = FakeScreen()
        with patch("deck_screens.select_from_list", return_value=(None, "i")):
            mapping = deck_screens.csv_mapping_screen(screen, csv_path)
        self.assertEqual(mapping["set_name"], "set_name")
        self.assertEqual(mapping["card_name"], "card_name")

    def test_import_screen_can_create_a_new_deck_from_text_input(self):
        txt_path = os.path.join(self.tmpdir.name, "source.txt")
        with open(txt_path, "w", encoding="utf-8") as fhand:
            fhand.write("---\nTOPIC: science\nAtom\nSmallest unit of matter\n---\n")
        screen = FakeScreen([ord("n"), ord("q")])
        with patch("deck_screens.text_input", side_effect=[txt_path, "study"]), patch(
            "curses.color_pair", return_value=0
        ):
            deck_screens.import_screen(screen, config.load_config())
        imported = storage.read_sko("study.sko", config.load_config())
        self.assertIn("science", imported)
        self.assertEqual(imported["science"][0]["card_name"], "Atom")

    def test_export_screen_writes_the_requested_json_file(self):
        storage.write_sko("study.sko", {"science": [new_card("Atom", "Matter")]}, config.load_config())
        output_path = os.path.join(self.tmpdir.name, "study.json")
        screen = FakeScreen([ord("j"), ord("q")])
        with patch("deck_screens.select_sko_file", return_value="study.sko"), patch(
            "deck_screens.text_input", return_value=output_path
        ), patch("curses.color_pair", return_value=0):
            deck_screens.export_screen(screen, config.load_config())
        self.assertTrue(os.path.exists(output_path))


if __name__ == "__main__":
    unittest.main()
