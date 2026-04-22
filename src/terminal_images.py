from __future__ import annotations

import base64
import io
import os
import sys

from rich_content import fetch_image_payload

_TRUTHY = {"1", "true", "yes", "on", "y"}
_KITTY_BODY_CACHE: dict[tuple[str, int, int], str] = {}


def _enabled_env(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in _TRUTHY


def terminal_supports_graphics() -> bool:
    if _enabled_env("SENKO_DISABLE_NATIVE_IMAGES"):
        return False
    stdout = getattr(sys, "__stdout__", None)
    if stdout is None or not hasattr(stdout, "isatty") or not stdout.isatty():
        return False
    if os.environ.get("TMUX") and not _enabled_env("SENKO_NATIVE_IMAGES_IN_TMUX"):
        return False
    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if term_program == "ghostty":
        return True
    if "kitty" in term:
        return True
    if "ghostty" in term:
        return True
    return False


def _emit(sequence: str) -> None:
    stdout = getattr(sys, "__stdout__", None)
    if stdout is None:
        return
    try:
        stdout.write(sequence)
        stdout.flush()
    except Exception:
        return


def clear_native_images() -> None:
    if not terminal_supports_graphics():
        return
    _emit("\x1b_Ga=d,d=A;\x1b\\")


def _build_kitty_body(url: str, payload: bytes, *, width_cells: int, height_cells: int) -> str | None:
    cache_key = (url, width_cells, height_cells)
    if cache_key in _KITTY_BODY_CACHE:
        return _KITTY_BODY_CACHE[cache_key]
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        image = Image.open(io.BytesIO(payload)).convert("RGBA")
    except Exception:
        return None
    target_width_px = max(32, width_cells * 8)
    target_height_px = max(32, height_cells * 16)
    image.thumbnail((target_width_px, target_height_px))
    # Draw onto an opaque canvas so transparent/unused regions do not leak
    # underlying text fallback lines in terminal overlays.
    canvas = Image.new("RGBA", (target_width_px, target_height_px), (0, 0, 0, 255))
    offset_x = max(0, (target_width_px - image.width) // 2)
    offset_y = max(0, (target_height_px - image.height) // 2)
    canvas.paste(image, (offset_x, offset_y), image)
    output = canvas.convert("RGB")
    buffer = io.BytesIO()
    try:
        output.save(buffer, format="PNG")
    except Exception:
        return None
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    chunk_size = 4096
    chunks = [encoded[i : i + chunk_size] for i in range(0, len(encoded), chunk_size)] or [""]
    parts = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        if index == 0:
            parts.append(
                f"\x1b_Ga=T,f=100,c={width_cells},r={height_cells},q=2,m={more};{chunk}\x1b\\"
            )
        else:
            parts.append(f"\x1b_Gm={more};{chunk}\x1b\\")
    body = "".join(parts)
    _KITTY_BODY_CACHE[cache_key] = body
    return body


def render_native_image(url: str, *, row: int, col: int, width_cells: int, height_cells: int) -> bool:
    if not terminal_supports_graphics() or not url:
        return False
    payload, _error, _note = fetch_image_payload(url)
    if payload is None:
        return False
    width_cells = max(4, width_cells)
    height_cells = max(2, height_cells)
    body = _build_kitty_body(url, payload, width_cells=width_cells, height_cells=height_cells)
    if body is None:
        return False
    row = max(0, row)
    col = max(0, col)
    # Save cursor, place image at target cell, then restore cursor for curses input.
    _emit(f"\x1b7\x1b[{row + 1};{col + 1}H{body}\x1b8")
    return True
