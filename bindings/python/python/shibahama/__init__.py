# SPDX-License-Identifier: MIT

"""Python bindings for Shibahama."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Callable, Mapping, Sequence

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

    def memory_items(self) -> list[MemoryItem]:
        return self._inner.memory_items()

    def export_records(self) -> list[dict[str, object]]:
        return [
            {
                "id": item.id,
                "content": item.content,
                "kind": item.kind,
                "source_kind": item.provenance.source_kind,
                "source_ref": item.provenance.source_ref,
                "ingested_by": item.provenance.ingested_by,
                "tier": item.tier,
                "credence": item.credence,
                "significance": item.significance,
                "credence_floor": item.credence_floor,
                "valid_from_unix": item.valid_from_unix,
                "valid_to_unix": item.valid_to_unix,
                "ingested_at_unix": item.ingested_at_unix,
            }
            for item in self.memory_items()
        ]

    def to_pandas(self):
        import pandas as pd

        return pd.DataFrame.from_records(self.export_records())

    def to_arrow(self):
        import pyarrow as pa

        return pa.Table.from_pylist(self.export_records())

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


class LangChainMemory:
    """Dependency-free LangChain-style memory adapter."""

    __slots__ = (
        "embed",
        "engine",
        "input_key",
        "memory_key",
        "output_key",
        "top_k",
    )

    def __init__(
        self,
        engine: Shibahama,
        embed: Callable[[str], Sequence[float]],
        memory_key: str = "history",
        input_key: str = "input",
        output_key: str = "output",
        top_k: int = 5,
    ) -> None:
        self.engine = engine
        self.embed = embed
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self.top_k = top_k

    @property
    def memory_variables(self) -> list[str]:
        return [self.memory_key]

    def load_memory_variables(self, inputs: Mapping[str, Any]) -> dict[str, str]:
        query = _mapping_text(inputs, self.input_key)
        candidates = self.engine.recall(self.embed(query), self.top_k)
        history = "\n".join(candidate.item.content for candidate in candidates)

        return {self.memory_key: history}

    async def aload_memory_variables(self, inputs: Mapping[str, Any]) -> dict[str, str]:
        return await asyncio.to_thread(self.load_memory_variables, inputs)

    def save_context(self, inputs: Mapping[str, Any], outputs: Mapping[str, Any]) -> None:
        user_text = _mapping_text(inputs, self.input_key)
        assistant_text = _mapping_text(outputs, self.output_key)
        content = f"Human: {user_text}\nAI: {assistant_text}"

        self.engine.write(
            content,
            vector=self.embed(content),
            source_kind="tool",
            source_ref="langchain",
            ingested_by="langchain",
        )

    async def asave_context(
        self, inputs: Mapping[str, Any], outputs: Mapping[str, Any]
    ) -> None:
        await asyncio.to_thread(self.save_context, inputs, outputs)

    def clear(self) -> None:
        return None

    async def aclear(self) -> None:
        return None


def _mapping_text(mapping: Mapping[str, Any], preferred_key: str) -> str:
    if preferred_key in mapping:
        return str(mapping[preferred_key])
    if mapping:
        return str(next(iter(mapping.values())))

    return ""


__all__ = [
    "__version__",
    "LangChainMemory",
    "MemoryItem",
    "Provenance",
    "RecallCandidate",
    "RecallStream",
    "Shibahama",
    "SignificanceBreakdown",
    "WhyTrace",
    "version",
]
