from __future__ import annotations

import re
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
    result = re.sub(r"\s+", " ", result)
    return result.strip()


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
            if render_latex:
                latex_text = _latex_to_text(latex_text)
            styled_lines.append([("Math", "muted")])
            for latex_line in (latex_text.splitlines() or [""]):
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
