# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import LETTER  # type: ignore[import-untyped]
from reportlab.pdfbase.pdfmetrics import stringWidth  # type: ignore[import-untyped]
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]

OUTPUT = Path("output/pdf/solomon-one-pager.pdf")


def _draw_wrapped(canvas: Canvas, text: str, x: float, y: float, width: float, leading: float) -> float:
    words = text.split()
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if stringWidth(candidate, "Helvetica", 9) > width and line:
            canvas.drawString(x, y, line)
            y -= leading
            line = word
        else:
            line = candidate
    if line:
        canvas.drawString(x, y, line)
        y -= leading
    return y


def _section(canvas: Canvas, title: str, body: str, x: float, y: float, width: float) -> float:
    canvas.setFont("Helvetica-Bold", 10)
    canvas.setFillColor(HexColor("#102A43"))
    canvas.drawString(x, y, title)
    y -= 14
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(HexColor("#1F2937"))
    return _draw_wrapped(canvas, body, x, y, width, 12) - 8


def render(destination: Path = OUTPUT) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(destination), pagesize=LETTER)
    page_width, page_height = LETTER
    canvas.setFillColor(HexColor("#102A43"))
    canvas.rect(0, page_height - 112, page_width, 112, fill=1, stroke=0)
    canvas.setFillColor(HexColor("#D5F249"))
    canvas.setFont("Helvetica-Bold", 23)
    canvas.drawString(48, page_height - 58, "solomon")
    canvas.setFillColor(HexColor("#FFFFFF"))
    canvas.setFont("Helvetica", 12)
    canvas.drawString(48, page_height - 82, "MCP-native currency infrastructure for verified legal knowledge")
    left_x, right_x, column_width = 48, 318, 220
    left_y = page_height - 142
    left_y = _section(
        canvas,
        "THE PROBLEM",
        "Search can find a useful memo but cannot establish whether its authority moved, "
        "a later view superseded it, or a lawyer contested it.",
        left_x,
        left_y,
        column_width,
    )
    left_y = _section(
        canvas,
        "THE PRODUCT",
        "Solomon records provenance, valid and ingestion time, dependencies, verification, "
        "supersession, contestability, and metadata-only audit evidence.",
        left_x,
        left_y,
        column_width,
    )
    left_y = _section(
        canvas,
        "HOW IT FITS",
        "An MCP host calls preflight_context before prompt assembly, then uses why, impact, "
        "or audit_pack when human review is required.",
        left_x,
        left_y,
        column_width,
    )
    left_y = _section(
        canvas,
        "LIMITS",
        "Solomon does not decide the law, monitor every authority, or replace firm deployment, "
        "retention, confidentiality, and professional-responsibility controls.",
        left_x,
        left_y,
        column_width,
    )
    right_y = page_height - 142
    canvas.setFont("Helvetica-Bold", 10)
    canvas.setFillColor(HexColor("#102A43"))
    canvas.drawString(right_x, right_y, "EVIDENCE PATH")
    right_y -= 17
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(HexColor("#1F2937"))
    for step in [
        "1. Boundary-review firm knowledge.",
        "2. Record or confirm dependencies.",
        "3. Register authority or internal changes.",
        "4. Propagate stale-pending-review state.",
        "5. Reaffirm, supersede, retire, or contest.",
        "6. Export a hash-verified audit pack.",
    ]:
        right_y = _draw_wrapped(canvas, step, right_x, right_y, column_width, 12) - 5
    right_y -= 3
    _section(
        canvas,
        "REVIEW QUESTIONS",
        "What is current? What changed? Which matters are affected? Who verified the position? "
        "What evidence supports reuse?",
        right_x,
        right_y,
        column_width,
    )
    canvas.setStrokeColor(HexColor("#CBD5E1"))
    canvas.line(48, 44, page_width - 48, 44)
    canvas.setFillColor(HexColor("#475569"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(48, 30, "solomon | Portfolio overview | See README, positioning, and known limitations")
    canvas.save()
    return destination


if __name__ == "__main__":
    render()
