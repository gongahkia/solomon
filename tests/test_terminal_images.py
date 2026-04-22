import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import terminal_images


class _FakeStdout:
    def __init__(self, tty: bool = True):
        self._tty = tty

    def isatty(self):
        return self._tty

    def write(self, _value):
        return None

    def flush(self):
        return None


class TerminalImageTests(unittest.TestCase):
    def test_supports_graphics_in_ghostty(self):
        env = {"TERM_PROGRAM": "ghostty", "TERM": "xterm-256color"}
        with patch.dict(os.environ, env, clear=True), patch.object(
            terminal_images.sys, "__stdout__", _FakeStdout(True)
        ):
            self.assertTrue(terminal_images.terminal_supports_graphics())

    def test_disables_graphics_in_tmux_without_override(self):
        env = {"TERM_PROGRAM": "ghostty", "TERM": "xterm-256color", "TMUX": "1"}
        with patch.dict(os.environ, env, clear=True), patch.object(
            terminal_images.sys, "__stdout__", _FakeStdout(True)
        ):
            self.assertFalse(terminal_images.terminal_supports_graphics())

    def test_allows_tmux_when_override_enabled(self):
        env = {
            "TERM_PROGRAM": "ghostty",
            "TERM": "xterm-256color",
            "TMUX": "1",
            "SENKO_NATIVE_IMAGES_IN_TMUX": "1",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(
            terminal_images.sys, "__stdout__", _FakeStdout(True)
        ):
            self.assertTrue(terminal_images.terminal_supports_graphics())


if __name__ == "__main__":
    unittest.main()
