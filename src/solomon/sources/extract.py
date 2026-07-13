# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from typing import Literal

from defusedxml import ElementTree  # type: ignore[import-untyped]
from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.sources.models import DocumentExtractionState

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 500


class ExtractedDocument(SolomonModel):
    text: str
    state: DocumentExtractionState
    reason: str | None = None
    mime_type: str
    metadata: dict[str, int | str] = Field(default_factory=dict)


def extract_document_bytes(data: bytes, *, filename: str, mime_type: str | None = None) -> ExtractedDocument:
    if len(data) > MAX_DOCUMENT_BYTES:
        return ExtractedDocument(
            text="",
            state=DocumentExtractionState.REJECTED,
            reason="document exceeds extraction byte limit",
            mime_type=mime_type or _mime_for_filename(filename),
            metadata={"bytes": len(data)},
        )
    resolved_mime = mime_type or _mime_for_filename(filename)
    if resolved_mime == "text/plain":
        return _ready(data.decode("utf-8", errors="replace"), resolved_mime)
    if resolved_mime == "text/html":
        parser = _TextParser()
        parser.feed(data.decode("utf-8", errors="replace"))
        return _ready(parser.text(), resolved_mime)
    if resolved_mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx(data, resolved_mime)
    if resolved_mime == "application/pdf":
        return _extract_pdf(data, resolved_mime)
    return ExtractedDocument(
        text="",
        state=DocumentExtractionState.REJECTED,
        reason=f"unsupported document MIME type: {resolved_mime}",
        mime_type=resolved_mime,
        metadata={"bytes": len(data)},
    )


def candidate_claims_from_text(text: str, *, minimum_characters: int = 32) -> list[tuple[str, int, int]]:
    claims: list[tuple[str, int, int]] = []
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
        content = match.group(0).strip()
        if len(content) >= minimum_characters:
            start = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
            claims.append((content, start, start + len(content)))
    return claims


def _ready(text: str, mime_type: str, *, metadata: dict[str, int | str] | None = None) -> ExtractedDocument:
    normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()
    if not normalized:
        return ExtractedDocument(
            text="",
            state=DocumentExtractionState.REJECTED,
            reason="document contains no extractable text",
            mime_type=mime_type,
            metadata=metadata or {},
        )
    return ExtractedDocument(
        text=normalized,
        state=DocumentExtractionState.READY,
        mime_type=mime_type,
        metadata=metadata or {},
    )


def _extract_docx(data: bytes, mime_type: str) -> ExtractedDocument:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        return ExtractedDocument(
            text="",
            state=DocumentExtractionState.REJECTED,
            reason=f"invalid DOCX: {exc.__class__.__name__}",
            mime_type=mime_type,
        )
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = [
        "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
        for paragraph in root.iter(f"{namespace}p")
    ]
    return _ready(
        "\n\n".join(value for value in paragraphs if value),
        mime_type,
        metadata={"paragraphs": len(paragraphs)},
    )


def _extract_pdf(data: bytes, mime_type: str) -> ExtractedDocument:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        if len(reader.pages) > MAX_PDF_PAGES:
            return ExtractedDocument(
                text="",
                state=DocumentExtractionState.REJECTED,
                reason="PDF exceeds extraction page limit",
                mime_type=mime_type,
                metadata={"pages": len(reader.pages)},
            )
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return _ready(text, mime_type, metadata={"pages": len(reader.pages)})
    except Exception as exc:  # noqa: BLE001
        return ExtractedDocument(
            text="",
            state=DocumentExtractionState.REJECTED,
            reason=f"invalid PDF: {exc.__class__.__name__}",
            mime_type=mime_type,
        )


def _mime_for_filename(filename: str) -> Literal[
    "text/plain",
    "text/html",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]:
    lower = filename.lower()
    if lower.endswith((".html", ".htm")):
        return "text/html"
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "text/plain"


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._parts.append("\n")

    def text(self) -> str:
        return "".join(self._parts)
