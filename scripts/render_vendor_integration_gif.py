# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _font(size: int) -> Any:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _frame(title: str, left: list[str], right: list[str]) -> Image.Image:
    image = Image.new("RGB", (1200, 630), "#0f172a")
    draw = ImageDraw.Draw(image)
    title_font = _font(34)
    body_font = _font(22)
    draw.rectangle((0, 0, 1200, 72), fill="#111827")
    draw.text((36, 18), title, fill="#f8fafc", font=title_font)
    draw.rectangle((36, 108, 570, 570), fill="#3f1d2e")
    draw.rectangle((630, 108, 1164, 570), fill="#123b38")
    draw.text((72, 140), "WITHOUT SOLOMON", fill="#fecdd3", font=title_font)
    draw.text((666, 140), "WITH SOLOMON", fill="#bbf7d0", font=title_font)
    for x, lines, accent in ((72, left, "#fee2e2"), (666, right, "#d1fae5")):
        y = 210
        for line in lines:
            draw.text((x, y), line, fill=accent, font=body_font)
            y += 48
    return image


def render(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        _frame(
            "VellumRelay calls Solomon before drafting",
            ["Prior memo cached", "Structure X may rely on", "Regulation R section 12"],
            ["preflight_context", "Current memo injected", "Draft begins with live context"],
        ),
        _frame(
            "Authority change: Regulation R section 12",
            ["Cache is unchanged", "No dependency check", "Stale text remains available"],
            ["Dependency change registered", "Currency state becomes", "STALE_PENDING_REVERIFICATION"],
        ),
        _frame(
            "Drafting after the change",
            ["Confidently reuses", "stale firm memo", "MISS"],
            ["No stale text injected", "Explains moved dependency", "Routes to re-verification"],
        ),
    ]
    frames[0].save(destination, save_all=True, append_images=frames[1:], duration=1600, loop=0, optimize=True)
    return destination


def main() -> int:
    render(Path("docs/assets/vendor-integration-demo.gif"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
