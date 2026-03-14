import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import main
import storage
from schema import new_card


class FakeScreen:
    def erase(self):
        return None

    def getmaxyx(self):
        return (24, 80)

    def addstr(self, y, x, text, attr=0):
        return None

    def refresh(self):
        return None

    def getch(self):
        return ord("q")

    def move(self, y, x):
        return None

    def clrtoeol(self):
        return None


class MainTUITests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_config_path = config.CONFIG_PATH
        self.original_storage_dir = storage.CONFIG_DIR
        config.CONFIG_PATH = os.path.join(self.tmpdir.name, "config.json")
        storage.CONFIG_DIR = os.path.join(self.tmpdir.name, "decks")
        self.screen = FakeScreen()

    def tearDown(self):
        config.CONFIG_PATH = self.original_config_path
        storage.CONFIG_DIR = self.original_storage_dir
        self.tmpdir.cleanup()

    def test_menu_sko_routes_review_to_direct_review_deck_screen(self):
        with patch("main.select_from_list", side_effect=[0, 7]), patch(
            "main.select_sko_file", return_value="study.sko"
        ), patch("main.deck_screen") as deck_screen:
            main.menu_sko(self.screen)
        deck_screen.assert_called_once()
        self.assertTrue(deck_screen.call_args.kwargs["direct_review"])

    def test_menu_sko_routes_browse_to_standard_deck_screen(self):
        with patch("main.select_from_list", side_effect=[1, 7]), patch(
            "main.select_sko_file", return_value="study.sko"
        ), patch("main.deck_screen") as deck_screen:
            main.menu_sko(self.screen)
        deck_screen.assert_called_once()
        self.assertEqual(deck_screen.call_args.args[:2], (self.screen, "study.sko"))
        self.assertNotIn("direct_review", deck_screen.call_args.kwargs)

    def test_menu_sko_routes_secondary_actions(self):
        action_cases = [
            ("import", 2, "import_screen"),
            ("export", 3, "export_screen"),
            ("history", 4, "show_history_screen"),
            ("stats", 5, "show_stats_screen"),
            ("settings", 6, "config_editor"),
        ]
        for _, action_index, target_name in action_cases:
            with self.subTest(target=target_name):
                with patch("main.select_from_list", side_effect=[action_index, 7]), patch(
                    f"main.{target_name}"
                ) as target:
                    if target_name == "config_editor":
                        target.return_value = config.load_config()
                    main.menu_sko(self.screen)
                target.assert_called_once()

    def test_deck_screen_direct_review_writes_updated_cards(self):
        original = new_card("Atom", "Matter")
        updated = dict(original)
        updated["card_info"] = "Updated"
        storage.write_sko("study.sko", {"science": [original]}, config.load_config())
        with patch("main.select_flashcard_set", return_value=("science", [original])), patch(
            "main.render_review_session", return_value=("science", [updated])
        ):
            main.deck_screen(self.screen, "study.sko", config.load_config(), direct_review=True)
        stored = storage.read_sko("study.sko", config.load_config())
        self.assertEqual(stored["science"][0]["card_info"], "Updated")

    def test_deck_screen_manage_path_writes_updated_sets(self):
        card = new_card("Atom", "Matter")
        storage.write_sko("study.sko", {"science": [card]}, config.load_config())
        updated_sets = {"science": [dict(card, card_info="Edited")]}
        with patch("main.select_flashcard_set", side_effect=[("science", [card]), None]), patch(
            "main.select_from_list", return_value=1
        ), patch("main.manage_cards_loop", return_value=("science", updated_sets)):
            main.deck_screen(self.screen, "study.sko", config.load_config())
        stored = storage.read_sko("study.sko", config.load_config())
        self.assertEqual(stored["science"][0]["card_info"], "Edited")

    def test_manage_cards_loop_adds_card_to_empty_set(self):
        sets = {"science": []}
        created = new_card("Atom", "Matter")
        with patch("main.select_from_list", side_effect=[(0, "a"), None]), patch(
            "main.add_sko_card", return_value=created
        ):
            _, updated_sets = main.manage_cards_loop(self.screen, sets, "science", config.load_config())
        self.assertEqual(len(updated_sets["science"]), 1)
        self.assertEqual(updated_sets["science"][0]["card_name"], "Atom")

    def test_manage_cards_loop_duplicate_action_inserts_copy(self):
        card = new_card("Atom", "Matter")
        sets = {"science": [card]}
        with patch("main.select_from_list", side_effect=[0, 1, None]):
            _, updated_sets = main.manage_cards_loop(self.screen, sets, "science", config.load_config())
        self.assertEqual(len(updated_sets["science"]), 2)
        self.assertEqual(updated_sets["science"][0]["card_name"], "Atom")
        self.assertEqual(updated_sets["science"][1]["card_name"], "Atom (copy)")

    def test_manage_cards_loop_move_action_can_empty_current_set(self):
        card = new_card("Atom", "Matter")
        sets = {"science": [card], "physics": []}
        with patch("main.select_from_list", side_effect=[0, 2, None]), patch(
            "main.choose_target_set", return_value="physics"
        ), patch("main.show_message") as show_message:
            _, updated_sets = main.manage_cards_loop(self.screen, sets, "science", config.load_config())
        self.assertEqual(updated_sets["science"], [])
        self.assertEqual(updated_sets["physics"][0]["card_name"], "Atom")
        show_message.assert_called_once()

    def test_manage_cards_loop_boundary_actions_show_messages(self):
        for action in (3, 4):
            with self.subTest(action=action):
                card = new_card("Atom", "Matter")
                sets = {"science": [card]}
                with patch("main.select_from_list", side_effect=[0, action, None]), patch(
                    "main.show_message"
                ) as show_message:
                    main.manage_cards_loop(self.screen, sets, "science", config.load_config())
                show_message.assert_called_once()

    def test_manage_cards_loop_edit_suspend_reset_and_delete_actions(self):
        edit_source = new_card("Atom", "Matter")
        edited = dict(edit_source)
        edited["card_info"] = "Edited"
        with patch("main.select_from_list", side_effect=[0, 0, None]), patch(
            "main.edit_sko_card", return_value=edited
        ):
            _, edit_sets = main.manage_cards_loop(self.screen, {"science": [edit_source]}, "science", config.load_config())
        self.assertEqual(edit_sets["science"][0]["card_info"], "Edited")

        suspend_source = new_card("Atom", "Matter")
        with patch("main.select_from_list", side_effect=[0, 5, None]):
            _, suspend_sets = main.manage_cards_loop(
                self.screen, {"science": [suspend_source]}, "science", config.load_config()
            )
        self.assertTrue(suspend_sets["science"][0]["suspended"])

        reset_source = new_card("Atom", "Matter")
        reset_source["state"] = "review"
        reset_source["interval"] = 7
        with patch("main.select_from_list", side_effect=[0, 6, None]):
            _, reset_sets = main.manage_cards_loop(
                self.screen, {"science": [reset_source]}, "science", config.load_config()
            )
        self.assertEqual(reset_sets["science"][0]["state"], "new")
        self.assertEqual(reset_sets["science"][0]["interval"], 0)

        delete_source = new_card("Atom", "Matter")
        with patch("main.select_from_list", side_effect=[0, 7, None]), patch(
            "main.confirm_prompt", return_value=True
        ):
            _, delete_sets = main.manage_cards_loop(
                self.screen, {"science": [delete_source]}, "science", config.load_config()
            )
        self.assertEqual(delete_sets["science"], [])


if __name__ == "__main__":
    unittest.main()
