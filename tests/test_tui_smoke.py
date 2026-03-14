import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import history
import history_view
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

    def test_history_screen_can_export_events(self):
        card = new_card("Question", "Answer")
        history.log_review_event("study.sko", "set_a", card, dict(card), 2, "due")
        export_path = os.path.join(self.tmpdir.name, "history.json")
        screen = FakeScreen([ord("e"), ord("q")])
        with patch("curses.color_pair", return_value=0), patch(
            "history_view.text_input", return_value=export_path
        ), patch("history_view.show_message"):
            history_view.show_history_screen(screen, config.load_config())
        self.assertTrue(os.path.exists(export_path))

    def test_history_screen_can_prune_all_events(self):
        card = new_card("Question", "Answer")
        history.log_review_event("study.sko", "set_a", card, dict(card), 2, "due")
        screen = FakeScreen([ord("p")])
        with patch("curses.color_pair", return_value=0), patch(
            "history_view.confirm_prompt", return_value=True
        ), patch("history_view.show_message"):
            history_view.show_history_screen(screen, config.load_config())
        self.assertEqual(history.load_history(), [])

    def test_history_screen_filters_export_scope_by_deck(self):
        first = new_card("Question", "Answer")
        second = new_card("Other", "Back")
        history.log_review_event("study.sko", "set_a", first, dict(first), 2, "due")
        history.log_review_event("other.sko", "set_b", second, dict(second), 1, "all")
        export_path = os.path.join(self.tmpdir.name, "study-history.jsonl")
        screen = FakeScreen([ord("f"), ord("e"), ord("q")])
        with patch("curses.color_pair", return_value=0), patch(
            "history_view.text_input",
            side_effect=["study", "", "", export_path],
        ), patch("history_view.show_message"):
            history_view.show_history_screen(screen, config.load_config())
        with open(export_path, "r", encoding="utf-8") as fhand:
            lines = [line for line in fhand.read().splitlines() if line]
        self.assertEqual(len(lines), 1)
        self.assertIn("study.sko", lines[0])


if __name__ == "__main__":
    unittest.main()
