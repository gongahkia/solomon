# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

ASSET_DIR = Path("docs/assets/console")
FRAME_SIZE = (960, 640)
SOURCE_SIZE = (1440, 960)


@dataclass(frozen=True)
class FrameMark:
    cursor: tuple[int, int]
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class GifSpec:
    source: Path
    destination: Path
    marks: tuple[FrameMark, ...]


def _scale_point(point: tuple[int, int]) -> tuple[int, int]:
    return (point[0] * FRAME_SIZE[0] // SOURCE_SIZE[0], point[1] * FRAME_SIZE[1] // SOURCE_SIZE[1])


def _scale_box(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1 = _scale_point((box[0], box[1]))
    x2, y2 = _scale_point((box[2], box[3]))
    return x1, y1, x2, y2


def _cursor(draw: ImageDraw.ImageDraw, point: tuple[int, int]) -> None:
    x, y = point
    shape = [
        (x, y),
        (x, y + 28),
        (x + 8, y + 21),
        (x + 15, y + 35),
        (x + 22, y + 31),
        (x + 15, y + 18),
        (x + 27, y + 18),
    ]
    draw.polygon(shape, fill="#ffffff", outline="#111827")


def _frame(base: Image.Image, mark: FrameMark) -> Image.Image:
    image = base.copy()
    draw = ImageDraw.Draw(image)
    box = _scale_box(mark.box)
    draw.rounded_rectangle(box, radius=8, outline="#2563eb", width=3)
    _cursor(draw, _scale_point(mark.cursor))
    return image


def _render(spec: GifSpec) -> Path:
    base = Image.open(spec.source).convert("RGB").resize(FRAME_SIZE, Image.Resampling.LANCZOS)
    frames = [_frame(base, mark) for mark in spec.marks]
    spec.destination.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        spec.destination,
        save_all=True,
        append_images=frames[1:],
        duration=900,
        loop=0,
        optimize=True,
    )
    return spec.destination


def render_all() -> list[Path]:
    specs = [
        GifSpec(
            source=ASSET_DIR / "verification-desk.png",
            destination=ASSET_DIR / "verification-desk.gif",
            marks=(
                FrameMark(cursor=(48, 190), box=(18, 170, 520, 260)),
                FrameMark(cursor=(622, 417), box=(565, 370, 1422, 584)),
                FrameMark(cursor=(680, 552), box=(580, 535, 770, 570)),
            ),
        ),
        GifSpec(
            source=ASSET_DIR / "dependency-review.png",
            destination=ASSET_DIR / "dependency-review.gif",
            marks=(
                FrameMark(cursor=(44, 216), box=(18, 205, 528, 336)),
                FrameMark(cursor=(438, 318), box=(414, 302, 528, 336)),
                FrameMark(cursor=(884, 142), box=(854, 119, 1407, 244)),
            ),
        ),
        GifSpec(
            source=ASSET_DIR / "audit-pack.png",
            destination=ASSET_DIR / "audit-pack.gif",
            marks=(
                FrameMark(cursor=(43, 420), box=(18, 400, 475, 485)),
                FrameMark(cursor=(620, 282), box=(580, 265, 696, 342)),
                FrameMark(cursor=(838, 416), box=(821, 92, 1422, 506)),
            ),
        ),
    ]
    return [_render(spec) for spec in specs]


def main() -> int:
    for path in render_all():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
