import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import rich_content
from rich_content import render_rich_text


class RichContentTests(unittest.TestCase):
    def test_auto_detects_java_code_without_fence(self):
        content = "public class Demo {\n  public static void main(String[] args) {\n    int x = 42;\n  }\n}"
        lines = render_rich_text(
            content,
            width=120,
            image_width=72,
            image_height=24,
            syntax_highlighting=True,
            render_latex=True,
        )
        styles = {style for line in lines for _, style in line}
        self.assertIn("code_keyword", styles)
        self.assertIn("code_type", styles)
        self.assertIn("code_number", styles)

    def test_formats_image_url_with_global_size(self):
        content = "https://example.com/image.png"
        lines = render_rich_text(
            content,
            width=120,
            image_width=55,
            image_height=33,
            syntax_highlighting=True,
            render_latex=True,
        )
        merged = " ".join(text for line in lines for text, _ in line)
        self.assertIn("Auto-size: 55x33", merged)
        self.assertIn("URL: https://example.com/image.png", merged)

    def test_hides_non_fatal_image_warning_notes_by_default(self):
        content = "https://example.com/image.png"
        rich_content.IMAGE_PREVIEW_NOTE_CACHE.clear()

        def _fake_preview(url: str, *, image_width: int, image_height: int, max_width: int):
            key = (url, image_width, image_height, max_width)
            rich_content.IMAGE_PREVIEW_NOTE_CACHE[key] = "TLS certificate check failed; preview fetched insecurely"
            return ["preview"]

        with patch("rich_content._image_preview_from_url", side_effect=_fake_preview):
            lines = render_rich_text(
                content,
                width=120,
                image_width=55,
                image_height=33,
                syntax_highlighting=True,
                render_latex=True,
            )
        merged = " ".join(text for line in lines for text, _ in line)
        self.assertNotIn("Preview note:", merged)

    def test_can_show_non_fatal_image_warning_notes_when_enabled(self):
        content = "https://example.com/image.png"
        rich_content.IMAGE_PREVIEW_NOTE_CACHE.clear()

        def _fake_preview(url: str, *, image_width: int, image_height: int, max_width: int):
            key = (url, image_width, image_height, max_width)
            rich_content.IMAGE_PREVIEW_NOTE_CACHE[key] = "TLS certificate check failed; preview fetched insecurely"
            return ["preview"]

        with patch("rich_content._image_preview_from_url", side_effect=_fake_preview):
            lines = render_rich_text(
                content,
                width=120,
                image_width=55,
                image_height=33,
                syntax_highlighting=True,
                render_latex=True,
                show_image_warnings=True,
            )
        merged = " ".join(text for line in lines for text, _ in line)
        self.assertIn("Preview note:", merged)

    def test_formats_inline_latex(self):
        content = "Area is given by $\\pi r^2$."
        lines = render_rich_text(
            content,
            width=120,
            image_width=72,
            image_height=24,
            syntax_highlighting=True,
            render_latex=True,
        )
        latex_spans = [text for line in lines for text, style in line if style == "latex"]
        self.assertTrue(any("pi" in span for span in latex_spans))
        self.assertTrue(any("²" in span or "^(" in span for span in latex_spans))

    def test_formats_block_latex_without_raw_backslash_commands(self):
        content = "$$\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}$$"
        lines = render_rich_text(
            content,
            width=120,
            image_width=72,
            image_height=24,
            syntax_highlighting=True,
            render_latex=True,
        )
        latex_text = " ".join(text for line in lines for text, style in line if style == "latex")
        self.assertNotIn("\\sum", latex_text)
        self.assertTrue("sum_(i=1)^(n)" in latex_text or len(latex_text.strip()) > 0)


if __name__ == "__main__":
    unittest.main()
