import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import review_flow


class ReviewFlowImageTests(unittest.TestCase):
    def test_parse_auto_size(self):
        self.assertEqual(review_flow._parse_auto_size("Auto-size: 72x24"), (72, 24))
        self.assertIsNone(review_flow._parse_auto_size("Auto-size: bad"))

    def test_collects_native_image_requests_from_styled_lines(self):
        styled_lines = [
            [("Image: Diagram", "image")],
            [("URL: https://example.com/diagram.png", "image")],
            [("Auto-size: 40x12", "image")],
            [("+----------------+", "image")],
            [("|image preview   |", "image")],
            [("+----------------+", "image")],
        ]
        requests = review_flow._collect_native_image_requests(
            styled_lines,
            start_row=3,
            end_row_exclusive=40,
            default_width=72,
            default_height=24,
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["url"], "https://example.com/diagram.png")
        self.assertEqual(requests[0]["row"], 6)
        self.assertEqual(requests[0]["width"], 40)
        self.assertEqual(requests[0]["height"], 12)

    def test_native_image_enabled_respects_config_and_terminal(self):
        config = {"tui": {"native_image_rendering": True}}
        with patch("review_flow.terminal_supports_graphics", return_value=True):
            self.assertTrue(review_flow._native_image_enabled(config))
        with patch("review_flow.terminal_supports_graphics", return_value=False):
            self.assertFalse(review_flow._native_image_enabled(config))
        with patch("review_flow.terminal_supports_graphics", return_value=True):
            self.assertFalse(review_flow._native_image_enabled({"tui": {"native_image_rendering": False}}))

    @unittest.skipIf(not getattr(review_flow.curses, "BUTTON1_CLICKED", 0), "curses mouse constants unavailable")
    def test_mouse_button_recognizes_left_click(self):
        with patch("review_flow.curses.getmouse", return_value=(0, 10, 5, 0, review_flow.curses.BUTTON1_CLICKED)):
            self.assertEqual(review_flow._mouse_button(review_flow.curses.KEY_MOUSE), "left")

    @unittest.skipIf(not getattr(review_flow.curses, "BUTTON3_CLICKED", 0), "curses right mouse constants unavailable")
    def test_mouse_button_recognizes_right_click(self):
        with patch("review_flow.curses.getmouse", return_value=(0, 10, 5, 0, review_flow.curses.BUTTON3_CLICKED)):
            self.assertEqual(review_flow._mouse_button(review_flow.curses.KEY_MOUSE), "right")

    @unittest.skipIf(not getattr(review_flow.curses, "BUTTON5_PRESSED", 0), "curses wheel constants unavailable")
    def test_mouse_event_recognizes_wheel_down(self):
        with patch("review_flow.curses.getmouse", return_value=(0, 10, 5, 0, review_flow.curses.BUTTON5_PRESSED)):
            self.assertEqual(review_flow._mouse_event(review_flow.curses.KEY_MOUSE), "wheel_down")

    def test_grade_footer_combines_click_with_selected_grade(self):
        footer = review_flow._grade_footer(2, False)
        self.assertIn("[3/Click] Good", footer)
        self.assertNotIn("[Click] Good", footer)


if __name__ == "__main__":
    unittest.main()
