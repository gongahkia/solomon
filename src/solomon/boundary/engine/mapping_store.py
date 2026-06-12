# SPDX-License-Identifier: Apache-2.0
"""Volatile Kaypoh-style mapping store vendored into Solomon."""

from __future__ import annotations

from dataclasses import dataclass, field

from solomon.boundary.engine.schemas import MappingEntry


@dataclass
class VolatileMappingStore:
    _mappings: dict[str, list[MappingEntry]] = field(default_factory=dict)

    def put(self, context_id: str, mapping: list[MappingEntry]) -> None:
        self._mappings[context_id] = list(mapping)

    def pop(self, context_id: str) -> list[MappingEntry] | None:
        return self._mappings.pop(context_id, None)

    def get(self, context_id: str) -> list[MappingEntry] | None:
        stored = self._mappings.get(context_id)
        return list(stored) if stored is not None else None

    def count(self) -> int:
        return len(self._mappings)
