from __future__ import annotations

import io
import re
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

StyledSpan = tuple[str, str]
StyledLine = list[StyledSpan]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif"}
IMAGE_LINE_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<url>https?://[^)\s]+)\)$")
URL_RE = re.compile(r"^https?://\S+$")
INLINE_LATEX_RE = re.compile(r"(\$[^$\n]+\$|\\\([^\n]+?\\\))")

JAVA_KEYWORDS = {
    "abstract",
    "assert",
    "boolean",
    "break",
    "byte",
    "case",
    "catch",
    "char",
    "class",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extends",
    "final",
    "finally",
    "float",
    "for",
    "if",
    "implements",
    "import",
    "instanceof",
    "int",
    "interface",
    "long",
    "native",
    "new",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "short",
    "static",
    "strictfp",
    "super",
    "switch",
    "synchronized",
    "this",
    "throw",
    "throws",
    "transient",
    "try",
    "void",
    "volatile",
    "while",
    "var",
    "record",
    "sealed",
    "permits",
}

JAVA_TYPES = {
    "String",
    "Integer",
    "Long",
    "Double",
    "Float",
    "Boolean",
    "List",
    "Map",
    "Set",
    "ArrayList",
    "HashMap",
    "HashSet",
    "Optional",
    "Stream",
    "Object",
}

LATEX_REPLACEMENTS = {
    r"\alpha": "alpha",
    r"\beta": "beta",
    r"\gamma": "gamma",
    r"\delta": "delta",
    r"\epsilon": "epsilon",
    r"\theta": "theta",
    r"\lambda": "lambda",
    r"\mu": "mu",
    r"\pi": "pi",
    r"\sigma": "sigma",
    r"\omega": "omega",
    r"\times": "x",
    r"\cdot": "*",
    r"\neq": "!=",
    r"\leq": "<=",
    r"\geq": ">=",
    r"\infty": "infinity",
    r"\to": "->",
    r"\rightarrow": "->",
    r"\left": "",
    r"\right": "",
}

LATEX_COMMANDS = {
    "sum": "sum",
    "prod": "prod",
    "int": "int",
    "lim": "lim",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "log": "log",
    "ln": "ln",
    "cdot": "*",
    "cdots": "...",
    "ldots": "...",
}

SUPERSCRIPT_MAP = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
    "+": "⁺",
    "-": "⁻",
    "=": "⁼",
    "(": "⁽",
    ")": "⁾",
}

IMAGE_PREVIEW_CACHE: dict[tuple[str, int, int, int], list[str] | None] = {}
IMAGE_PREVIEW_ERROR_CACHE: dict[tuple[str, int, int, int], str | None] = {}
LATEX_PREVIEW_CACHE: dict[tuple[str, int], list[str] | None] = {}


def _is_image_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def _parse_image_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    markdown_match = IMAGE_LINE_RE.match(stripped)
    if markdown_match:
        url = markdown_match.group("url")
        if _is_image_url(url):
            return (markdown_match.group("alt") or "Image", url)
    if URL_RE.match(stripped) and _is_image_url(stripped):
        return ("Image", stripped)
    return None


def _looks_like_java(lines: list[str]) -> bool:
    joined = "\n".join(lines)
    java_markers = ["System.out", "public class", "private", "extends", "implements", "import java", "@Override"]
    if any(marker in joined for marker in java_markers):
        return True
    java_words = 0
    for word in re.findall(r"[A-Za-z_]\w*", joined):
        if word in JAVA_KEYWORDS or word in JAVA_TYPES:
            java_words += 1
    if java_words >= 3:
        return True
    return False


def _looks_like_code(lines: list[str]) -> bool:
    if not lines:
        return False
    code_signals = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith((";", "{", "}")):
            code_signals += 1
        if re.search(r"\b(if|for|while|class|return|public|private|static|void|int|String)\b", stripped):
            code_signals += 1
        if "//" in stripped or "/*" in stripped or "*/" in stripped:
            code_signals += 1
        if re.search(r"[{}();=<>]", stripped):
            code_signals += 1
    return code_signals >= max(2, len(lines))


def _latex_to_text(content: str) -> str:
    result = content.strip()
    for source, target in LATEX_REPLACEMENTS.items():
        result = result.replace(source, target)
    result = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", result)
    result = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", result)
    result = re.sub(
        r"\\([A-Za-z]+)",
        lambda match: LATEX_COMMANDS.get(match.group(1), match.group(1)),
        result,
    )
    result = re.sub(r"_\{([^{}]+)\}", r"_(\1)", result)
    result = re.sub(r"\^\{([^{}]+)\}", r"^(\1)", result)
    result = re.sub(r"_([A-Za-z0-9]+)", r"_(\1)", result)
    result = re.sub(r"\^([A-Za-z0-9]+)", r"^(\1)", result)
    result = re.sub(
        r"\^\(([\d+\-=()]+)\)",
        lambda match: "".join(SUPERSCRIPT_MAP.get(char, char) for char in match.group(1)),
        result,
    )
    result = result.replace("{", "").replace("}", "")
    result = re.sub(r"\s+", " ", result)
    return result.strip()


def _image_preview_placeholder(image_width: int, image_height: int, *, max_width: int) -> list[str]:
    preview_width = max(14, min(max_width, image_width))
    preview_height = max(3, min(8, max(3, image_height // 4)))
    inner_width = max(2, preview_width - 2)
    top = "+" + "-" * inner_width + "+"
    middle_rows = []
    label = " image preview "
    label = label[:inner_width]
    label_start = max(0, (inner_width - len(label)) // 2)
    for row in range(preview_height - 2):
        if row == (preview_height - 2) // 2:
            line = " " * label_start + label + " " * max(0, inner_width - label_start - len(label))
            middle_rows.append("|" + line[:inner_width].ljust(inner_width) + "|")
        else:
            middle_rows.append("|" + " " * inner_width + "|")
    return [top, *middle_rows, top]


def _image_to_ascii(image, *, max_width: int, max_height: int) -> list[str]:
    target_width = max(8, min(max_width, image.width))
    target_height = max(4, min(max_height, image.height))
    if target_height > target_width * 2:
        target_height = max(4, target_width * 2)
    image = image.resize((target_width, target_height))
    ramp = " .:-=+*#%@"
    lines: list[str] = []
    for y in range(target_height):
        row_chars = []
        for x in range(target_width):
            pixel = image.getpixel((x, y))
            index = min(len(ramp) - 1, int((pixel / 255) * (len(ramp) - 1)))
            row_chars.append(ramp[index])
        lines.append("".join(row_chars))
    return lines


def _binary_ascii_from_image(image, *, max_width: int, max_height: int) -> list[str]:
    target_width = max(12, min(max_width, image.width))
    target_height = max(4, min(max_height, image.height))
    image = image.resize((target_width, target_height))
    matrix = []
    for y in range(target_height):
        row = []
        for x in range(target_width):
            row.append("█" if image.getpixel((x, y)) < 150 else " ")
        matrix.append(row)
    while matrix and not any(cell == "█" for cell in matrix[0]):
        matrix.pop(0)
    while matrix and not any(cell == "█" for cell in matrix[-1]):
        matrix.pop()
    if not matrix:
        return []
    left = 0
    right = len(matrix[0]) - 1
    while left <= right and not any(row[left] == "█" for row in matrix):
        left += 1
    while right >= left and not any(row[right] == "█" for row in matrix):
        right -= 1
    if left > right:
        return []
    lines = []
    for row in matrix:
        lines.append("".join(row[left : right + 1]).rstrip())
    return [line for line in lines if line.strip()]


def _image_preview_from_url(url: str, *, image_width: int, image_height: int, max_width: int) -> list[str] | None:
    cache_key = (url, image_width, image_height, max_width)
    if cache_key in IMAGE_PREVIEW_CACHE:
        return IMAGE_PREVIEW_CACHE[cache_key]
    try:
        from PIL import Image
    except Exception:
        IMAGE_PREVIEW_CACHE[cache_key] = None
        IMAGE_PREVIEW_ERROR_CACHE[cache_key] = "Pillow not installed"
        return None
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept": "image/*,*/*;q=0.8",
            },
        )
        with urlopen(request, timeout=6) as response:
            payload = response.read(2_000_000)
        image = Image.open(io.BytesIO(payload)).convert("L")
    except HTTPError as exc:
        IMAGE_PREVIEW_CACHE[cache_key] = None
        IMAGE_PREVIEW_ERROR_CACHE[cache_key] = f"HTTP {exc.code}"
        return None
    except URLError as exc:
        IMAGE_PREVIEW_CACHE[cache_key] = None
        reason = str(getattr(exc, "reason", "") or "").strip()
        IMAGE_PREVIEW_ERROR_CACHE[cache_key] = f"Network error ({reason})" if reason else "Network error"
        return None
    except Exception:
        IMAGE_PREVIEW_CACHE[cache_key] = None
        IMAGE_PREVIEW_ERROR_CACHE[cache_key] = "Image decode failed"
        return None
    lines = _image_to_ascii(image, max_width=max(8, min(max_width, image_width)), max_height=max(4, min(image_height, 18)))
    IMAGE_PREVIEW_CACHE[cache_key] = lines
    IMAGE_PREVIEW_ERROR_CACHE[cache_key] = None
    return lines


def _latex_preview_from_expression(expression: str, *, max_width: int) -> list[str] | None:
    expr = expression.strip()
    cache_key = (expr, max_width)
    if cache_key in LATEX_PREVIEW_CACHE:
        return LATEX_PREVIEW_CACHE[cache_key]
    try:
        from PIL import Image, ImageChops
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except Exception:
        LATEX_PREVIEW_CACHE[cache_key] = None
        return None
    if not expr:
        LATEX_PREVIEW_CACHE[cache_key] = None
        return None
    try:
        figure = Figure(figsize=(8, 2.5), dpi=200)
        canvas = FigureCanvasAgg(figure)
        ax = figure.add_subplot(111)
        ax.axis("off")
        ax.text(
            0.02,
            0.5,
            f"${expr}$",
            fontsize=24,
            va="center",
            ha="left",
            color="black",
        )
        canvas.draw()
        width, height = canvas.get_width_height()
        rgba = Image.frombuffer("RGBA", (width, height), canvas.buffer_rgba(), "raw", "RGBA", 0, 1)
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        image = white.convert("L")
        # Crop whitespace around rendered formula.
        inverted = ImageChops.invert(image)
        bbox = inverted.getbbox()
        if bbox:
            image = image.crop(bbox)
        lines = _binary_ascii_from_image(
            image,
            max_width=max(24, min(max_width, 56)),
            max_height=10,
        )
        if not lines:
            return None
    except Exception:
        LATEX_PREVIEW_CACHE[cache_key] = None
        return None
    LATEX_PREVIEW_CACHE[cache_key] = lines
    return lines


def _wrap_spans(spans: StyledLine, width: int) -> list[StyledLine]:
    if width < 1:
        width = 1
    lines: list[StyledLine] = []
    current: StyledLine = []
    remaining = width
    for text, style in spans:
        if not text:
            continue
        pending = text
        while pending:
            if remaining == 0:
                lines.append(current)
                current = []
                remaining = width
            take = pending[:remaining]
            current.append((take, style))
            pending = pending[remaining:]
            remaining -= len(take)
    if current or not lines:
        lines.append(current)
    return lines


def _tokenize_java_line(line: str, in_block_comment: bool) -> tuple[StyledLine, bool]:
    tokens: StyledLine = []
    index = 0
    length = len(line)
    while index < length:
        if in_block_comment:
            end = line.find("*/", index)
            if end == -1:
                tokens.append((line[index:], "code_comment"))
                return (tokens, True)
            tokens.append((line[index : end + 2], "code_comment"))
            index = end + 2
            in_block_comment = False
            continue
        if line.startswith("//", index):
            tokens.append((line[index:], "code_comment"))
            break
        if line.startswith("/*", index):
            end = line.find("*/", index + 2)
            if end == -1:
                tokens.append((line[index:], "code_comment"))
                return (tokens, True)
            tokens.append((line[index : end + 2], "code_comment"))
            index = end + 2
            continue
        char = line[index]
        if char in {'"', "'"}:
            quote = char
            end = index + 1
            escaped = False
            while end < length:
                current = line[end]
                if escaped:
                    escaped = False
                    end += 1
                    continue
                if current == "\\":
                    escaped = True
                    end += 1
                    continue
                if current == quote:
                    end += 1
                    break
                end += 1
            tokens.append((line[index:end], "code_string"))
            index = end
            continue
        if char == "@":
            end = index + 1
            while end < length and (line[end].isalnum() or line[end] == "_"):
                end += 1
            tokens.append((line[index:end], "code_annotation"))
            index = end
            continue
        if char.isdigit():
            end = index + 1
            while end < length and (line[end].isdigit() or line[end] in {".", "_"}):
                end += 1
            tokens.append((line[index:end], "code_number"))
            index = end
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < length and (line[end].isalnum() or line[end] == "_"):
                end += 1
            word = line[index:end]
            if word in JAVA_KEYWORDS:
                style = "code_keyword"
            elif word in JAVA_TYPES or (word and word[0].isupper()):
                style = "code_type"
            else:
                style = "code_default"
            tokens.append((word, style))
            index = end
            continue
        tokens.append((char, "code_default"))
        index += 1
    return (tokens, in_block_comment)


def _highlight_code_lines(lines: list[str], language: str) -> list[StyledLine]:
    highlighted: list[StyledLine] = []
    use_java = language == "java"
    in_block_comment = False
    for line in lines:
        if use_java:
            styled, in_block_comment = _tokenize_java_line(line, in_block_comment)
            highlighted.append(styled)
            continue
        if line.strip().startswith("#"):
            highlighted.append([(line, "code_comment")])
        else:
            highlighted.append([(line, "code_default")])
    return highlighted


def _inline_latex_spans(line: str, *, render_latex: bool) -> StyledLine:
    spans: StyledLine = []
    cursor = 0
    for match in INLINE_LATEX_RE.finditer(line):
        start, end = match.span()
        if start > cursor:
            spans.append((line[cursor:start], "default"))
        raw = match.group(0)
        content = raw.strip("$")
        if raw.startswith(r"\(") and raw.endswith(r"\)"):
            content = raw[2:-2]
        display = _latex_to_text(content) if render_latex else content
        spans.append((display, "latex"))
        cursor = end
    if cursor < len(line):
        spans.append((line[cursor:], "default"))
    if not spans:
        spans.append((line, "default"))
    return spans


def _render_text_paragraph(
    lines: list[str],
    width: int,
    *,
    render_latex: bool,
    syntax_highlighting: bool,
) -> list[StyledLine]:
    if syntax_highlighting and _looks_like_code(lines):
        language = "java" if _looks_like_java(lines) else "text"
        return _highlight_code_lines(lines, language)
    rendered: list[StyledLine] = []
    for line in lines:
        spans = _inline_latex_spans(line, render_latex=render_latex)
        rendered.extend(_wrap_spans(spans, width))
    return rendered


def render_rich_text(
    text: str,
    *,
    width: int,
    image_width: int,
    image_height: int,
    syntax_highlighting: bool = True,
    render_latex: bool = True,
) -> list[StyledLine]:
    lines = text.splitlines() or [""]
    styled_lines: list[StyledLine] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            language = stripped[3:].strip().lower() or "text"
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            styled_lines.append([("Code", "muted")])
            highlighted = _highlight_code_lines(code_lines, "java" if language in {"java", "jav"} else "text")
            for highlighted_line in highlighted or [[("", "code_default")]]:
                styled_lines.append(highlighted_line)
            if index < len(lines):
                index += 1
            continue
        image = _parse_image_line(line)
        if image is not None:
            alt, url = image
            styled_lines.extend(
                [
                    [(f"Image: {alt}", "image")],
                    [(f"URL: {url}", "image")],
                    [(f"Auto-size: {image_width}x{image_height}", "image")],
                ]
            )
            preview = _image_preview_from_url(
                url,
                image_width=image_width,
                image_height=image_height,
                max_width=max(14, min(width, image_width)),
            )
            if preview is None:
                reason = IMAGE_PREVIEW_ERROR_CACHE.get((url, image_width, image_height, max(14, min(width, image_width))))
                if reason:
                    styled_lines.append([(f"Preview unavailable: {reason}", "image")])
                preview = _image_preview_placeholder(
                    image_width,
                    image_height,
                    max_width=max(14, min(width, image_width)),
                )
            for preview_line in preview:
                styled_lines.append([(preview_line, "image")])
            index += 1
            continue
        if stripped.startswith("$$"):
            latex_parts = [stripped[2:]]
            index += 1
            while index < len(lines):
                current = lines[index].strip()
                if current.endswith("$$"):
                    latex_parts.append(current[:-2])
                    break
                latex_parts.append(lines[index])
                index += 1
            latex_text = "\n".join(part for part in latex_parts if part).strip()
            styled_lines.append([("Math", "muted")])
            ascii_preview = _latex_preview_from_expression(latex_text, max_width=max(12, width - 1)) if render_latex else None
            if ascii_preview:
                for latex_line in ascii_preview:
                    styled_lines.extend(_wrap_spans([(latex_line, "latex")], width))
            else:
                latex_display = _latex_to_text(latex_text) if render_latex else latex_text
                for latex_line in (latex_display.splitlines() or [""]):
                    styled_lines.extend(_wrap_spans([(latex_line, "latex")], width))
            index += 1
            continue
        if stripped == "":
            styled_lines.append([("", "default")])
            index += 1
            continue
        paragraph = [line]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if candidate.strip() == "" or candidate.strip().startswith("```"):
                break
            if _parse_image_line(candidate) is not None:
                break
            paragraph.append(candidate)
            index += 1
        styled_lines.extend(
            _render_text_paragraph(
                paragraph,
                width,
                render_latex=render_latex,
                syntax_highlighting=syntax_highlighting,
            )
        )
    return styled_lines


ANSI_MAP = {
    "default": "\033[0m",
    "muted": "\033[90m",
    "latex": "\033[95m",
    "image": "\033[96m",
    "code_default": "\033[37m",
    "code_keyword": "\033[36m",
    "code_type": "\033[94m",
    "code_string": "\033[92m",
    "code_number": "\033[93m",
    "code_comment": "\033[90m",
    "code_annotation": "\033[35m",
}


def styled_lines_to_ansi(lines: list[StyledLine]) -> list[str]:
    rendered = []
    for line in lines:
        parts = []
        for text, style in line:
            prefix = ANSI_MAP.get(style, ANSI_MAP["default"])
            parts.append(f"{prefix}{text}")
        parts.append(ANSI_MAP["default"])
        rendered.append("".join(parts))
    return rendered
