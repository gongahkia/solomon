import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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


if __name__ == "__main__":
    unittest.main()
