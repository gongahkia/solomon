# SPDX-License-Identifier: MIT

"""Python bindings for Shibahama."""

import asyncio
from collections.abc import AsyncIterator

from ._shibahama import (
    __version__,
    MemoryItem,
    Provenance,
    RecallCandidate,
    RecallStream,
    Shibahama as _NativeShibahama,
    SignificanceBreakdown,
    WhyTrace,
    version,
)


class Shibahama:
    """In-process Shibahama engine."""

    __slots__ = ("_inner",)

    def __init__(self, path: str, dimensions: int, capacity: int = 1024) -> None:
        self._inner = _NativeShibahama(path, dimensions, capacity)

    def write(
        self,
        content: str,
        vector=None,
        source_kind: str = "user",
        source_ref: str | None = None,
        ingested_by: str = "python",
        valid_from_unix: int | None = None,
        ingested_at_unix: int | None = None,
        kind: str = "fact",
        index_name: str = "default",
        model: str = "unknown",
        model_version: str = "unknown",
    ) -> MemoryItem:
        return self._inner.write(
            content,
            vector,
            source_kind,
            source_ref,
            ingested_by,
            valid_from_unix,
            ingested_at_unix,
            kind,
            index_name,
            model,
            model_version,
        )

    async def async_write(self, *args, **kwargs) -> MemoryItem:
        return await asyncio.to_thread(self.write, *args, **kwargs)

    def recall(
        self,
        query_vector,
        top_k: int,
        now_unix: int | None = None,
        raw_query_context: str | None = None,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> list[RecallCandidate]:
        return self._inner.recall(
            query_vector,
            top_k,
            now_unix,
            raw_query_context,
            include_cold,
            include_instructions,
        )

    async def async_recall(self, *args, **kwargs) -> list[RecallCandidate]:
        return await asyncio.to_thread(self.recall, *args, **kwargs)

    def stream_recall(
        self,
        query_vector,
        top_k: int,
        now_unix: int | None = None,
        raw_query_context: str | None = None,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> RecallStream:
        return self._inner.stream_recall(
            query_vector,
            top_k,
            now_unix,
            raw_query_context,
            include_cold,
            include_instructions,
        )

    async def async_stream_recall(self, *args, **kwargs) -> AsyncIterator[RecallCandidate]:
        candidates = await self.async_recall(*args, **kwargs)

        for candidate in candidates:
            yield candidate

    def timeline(
        self,
        query_vector,
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> list[RecallCandidate]:
        return self._inner.timeline(
            query_vector,
            top_k,
            as_of_unix,
            include_cold,
            include_instructions,
        )

    async def async_timeline(self, *args, **kwargs) -> list[RecallCandidate]:
        return await asyncio.to_thread(self.timeline, *args, **kwargs)

    def stream_timeline(
        self,
        query_vector,
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> RecallStream:
        return self._inner.stream_timeline(
            query_vector,
            top_k,
            as_of_unix,
            include_cold,
            include_instructions,
        )

    async def async_stream_timeline(self, *args, **kwargs) -> AsyncIterator[RecallCandidate]:
        candidates = await self.async_timeline(*args, **kwargs)

        for candidate in candidates:
            yield candidate

    def reinforce(self, memory_id: str, outcome: str = "cited") -> bool:
        return self._inner.reinforce(memory_id, outcome)

    async def async_reinforce(self, *args, **kwargs) -> bool:
        return await asyncio.to_thread(self.reinforce, *args, **kwargs)

    def why(self, memory_id: str, now_unix: int | None = None) -> WhyTrace | None:
        return self._inner.why(memory_id, now_unix)

    async def async_why(self, *args, **kwargs) -> WhyTrace | None:
        return await asyncio.to_thread(self.why, *args, **kwargs)


__all__ = [
    "__version__",
    "MemoryItem",
    "Provenance",
    "RecallCandidate",
    "RecallStream",
    "Shibahama",
    "SignificanceBreakdown",
    "WhyTrace",
    "version",
]
