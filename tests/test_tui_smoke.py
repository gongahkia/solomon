import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import history
import review_flow
import stats_view
import storage
import tui
from schema import new_card


class FakeScreen:
    def __init__(self, keys):
        self.keys = list(keys)

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

    def move(self, y, x):
        return None

    def clrtoeol(self):
        return None


class TUISmokeTests(unittest.TestCase):
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

    def test_select_from_list_smoke(self):
        screen = FakeScreen([ord("j"), 10])
        with patch("curses.color_pair", return_value=0):
            choice = tui.select_from_list(
                screen,
                "Choose",
                [("One", "", tui.COLORS["info"]), ("Two", "", tui.COLORS["success"])],
                footer="[Enter] Select",
            )
        self.assertEqual(choice, 1)

    def test_render_review_session_logs_history(self):
        cards = [new_card("Question", "Answer")]
        screen = FakeScreen([10, ord(" "), ord("3"), 10])
        with patch("curses.color_pair", return_value=0):
            _, updated_cards = review_flow.render_review_session(
                screen,
                "study.sko",
                "set_a",
                cards,
                config.load_config(),
            )
        self.assertEqual(len(updated_cards), 1)
        self.assertEqual(updated_cards[0]["good_count"], 1)
        self.assertEqual(len(history.load_history(deck_name="study.sko", set_name="set_a")), 1)

    def test_show_stats_screen_handles_navigation(self):
        card = new_card("Question", "Answer")
        history.log_review_event("study.sko", "set_a", card, dict(card), 2, "due")
        valid_statuses = [{"filename": "study.sko", "valid": True, "sets": {"set_a": [card]}}]
        screen = FakeScreen([ord("j"), ord("k"), ord("q")])
        with patch("curses.color_pair", return_value=0):
            stats_view.show_stats_screen(screen, valid_statuses, config.load_config())


if __name__ == "__main__":
    unittest.main()
