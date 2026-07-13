# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from solomon.contracts import AdapterHealth, DiscoveredDocument, SyncCheckpoint
from solomon.sources.models import DocumentSource, DocumentSourceKind


class FilesystemDocumentSourceAdapter:
    kind = DocumentSourceKind.FILESYSTEM

    def health(self, source: DocumentSource) -> AdapterHealth:
        root = Path(source.root_ref)
        if root.is_dir():
            return AdapterHealth(healthy=True)
        return AdapterHealth(healthy=False, detail="filesystem source root is not a readable directory")

    def discover(
        self,
        source: DocumentSource,
        checkpoint: SyncCheckpoint | None,
    ) -> tuple[list[DiscoveredDocument], SyncCheckpoint | None]:
        _ = checkpoint
        if source.kind is not DocumentSourceKind.FILESYSTEM:
            raise ValueError("filesystem adapter requires a filesystem source")
        root = Path(source.root_ref)
        if not root.is_dir():
            raise ValueError("filesystem source root is not a readable directory")
        include = _patterns(source.config.settings.get("include"), default=("**/*",), setting="include")
        exclude = _patterns(source.config.settings.get("exclude"), default=(), setting="exclude")
        documents: list[DiscoveredDocument] = []
        cursor_parts: list[str] = []
        for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if not _matches(relative, include) or _matches(relative, exclude):
                continue
            stat = path.stat()
            external_id = f"filesystem:{stat.st_dev}:{stat.st_ino}"
            documents.append(
                DiscoveredDocument(
                    external_id=external_id,
                    filename=path.name,
                    content_ref=path.resolve().as_uri(),
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    metadata={"relative_path": relative, "size": stat.st_size},
                )
            )
            cursor_parts.append(f"{external_id}:{stat.st_mtime_ns}:{stat.st_size}")
        return documents, SyncCheckpoint(source_id=source.id, cursor=_cursor(cursor_parts))


def _patterns(value: object, *, default: tuple[str, ...], setting: str) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not value:
        raise ValueError(f"filesystem source {setting} must be a non-empty list of patterns")
    patterns = tuple(value)
    if any(not isinstance(pattern, str) or not pattern for pattern in patterns):
        raise ValueError(f"filesystem source {setting} must be a non-empty list of patterns")
    return patterns


def _matches(relative_path: str, patterns: tuple[str, ...]) -> bool:
    path = PurePosixPath(relative_path)
    return any(
        pattern == "**/*"
        or path.match(pattern)
        or (pattern.startswith("**/") and path.match(pattern.removeprefix("**/")))
        or fnmatchcase(relative_path, pattern)
        for pattern in patterns
    )


def _cursor(parts: list[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


__all__ = ["FilesystemDocumentSourceAdapter"]
