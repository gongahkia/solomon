# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _frame(title: str, lines: list[str]) -> Image.Image:
    image = Image.new("RGB", (960, 540), "#0f172a")
    draw = ImageDraw.Draw(image)
    title_font = _font(34)
    body_font = _font(24)
    draw.rectangle((0, 0, 960, 72), fill="#111827")
    draw.text((36, 18), title, fill="#f8fafc", font=title_font)
    y = 112
    for line in lines:
        fill = "#fde68a" if "STALE" in line or "MISS" in line else "#d1fae5" if "Solomon" in line else "#e5e7eb"
        draw.text((48, y), line, fill=fill, font=body_font)
        y += 48
    return image


def render(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        _frame(
            "2023 house view ingested",
            [
                "Memo: structure X compliant under Regulation R section 12",
                "Matter: Client A / 2023 advice",
                "Dependency edge: memo -> reg-r-12",
            ],
        ),
        _frame(
            "2025 authority change",
            [
                "External feed: Regulation R section 12 amended",
                "Graph walk: reg-r-12 -> house-view memo",
                "Currency state: STALE_PENDING_REVERIFICATION",
            ],
        ),
        _frame(
            "2026 associate query",
            [
                "Warehouse baseline: returns memo with no staleness signal (MISS)",
                "Solomon: returns memo flagged STALE with dependency reason",
                "Kaypoh boundary: model prompt contains [CLIENT_1], not Client A",
            ],
        ),
    ]
    frames[0].save(
        destination,
        save_all=True,
        append_images=frames[1:],
        duration=1400,
        loop=0,
        optimize=True,
    )
    return destination


def main() -> int:
    render(Path("docs/assets/stale-house-view-demo.gif"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

