# SPDX-License-Identifier: MIT

"""Python bindings for Shibahama."""

import asyncio
import json
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
    capabilities_json,
    version,
)


def capabilities() -> dict[str, Any]:
    """Return the versioned capability document for this build."""
    return json.loads(capabilities_json())


class ShibahamaError(RuntimeError):
    """Structured error raised by the public Shibahama Python wrapper."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = _error_code(message)
        self.severity = "recoverable" if self.code in {"SHIBA_RECALL", "SHIBA_TASK"} else "fatal"
        self.retryable = self.severity == "recoverable"


def _error_code(message: str) -> str:
    start = message.find("[SHIBA_")
    end = message.find("]", start)
    return message[start + 1 : end] if start != -1 and end != -1 else "SHIBA_INTERNAL"


def _raise_structured(error: RuntimeError) -> None:
    if isinstance(error, ShibahamaError):
        raise error
    raise ShibahamaError(str(error)) from error


def _structured_errors(method):
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RuntimeError as error:
            _raise_structured(error)

    return wrapped


class Shibahama:
    """In-process Shibahama engine."""

    __slots__ = ("_inner",)

    def __init__(self, path: str, dimensions: int, capacity: int = 1024) -> None:
        """Open an embedded Shibahama store with the built-in HNSW vector index."""
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
        """Write a memory and optionally index an embedding vector."""
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
        """Async wrapper for `write` using a worker thread."""
        return await asyncio.to_thread(self.write, *args, **kwargs)

    def invalidate(self, memory_id: str, valid_to_unix: int) -> bool:
        """Invalidate a memory at a Unix timestamp without deleting its history."""
        return self._inner.invalidate(memory_id, valid_to_unix)

    async def async_invalidate(self, *args, **kwargs) -> bool:
        """Async wrapper for `invalidate` using a worker thread."""
        return await asyncio.to_thread(self.invalidate, *args, **kwargs)

    def recall(
        self,
        query_vector,
        top_k: int,
        now_unix: int | None = None,
        raw_query_context: str | None = None,
        include_cold: bool = False,
        include_instructions: bool = False,
        max_context_tokens: int | None = None,
        similarity_weight: float = 1.0,
        significance_weight: float = 1.0,
        recency_weight: float = 0.25,
        graph_weight: float = 0.25,
        related_memory_ids_by_anchor: Mapping[str, Sequence[str]] | None = None,
    ) -> list[RecallCandidate]:
        """Recall current memories for a query embedding."""
        return self._inner.recall(
            query_vector,
            top_k,
            now_unix,
            raw_query_context,
            include_cold,
            include_instructions,
            max_context_tokens,
            similarity_weight,
            significance_weight,
            recency_weight,
            graph_weight,
            related_memory_ids_by_anchor,
        )

    async def async_recall(self, *args, **kwargs) -> list[RecallCandidate]:
        """Async wrapper for `recall` using a worker thread."""
        return await asyncio.to_thread(self.recall, *args, **kwargs)

    def memory_items(self) -> list[MemoryItem]:
        """Return all current materialized memory rows."""
        return self._inner.memory_items()

    def event_records(self) -> dict[str, Any]:
        """Return durable event-log records."""
        return json.loads(self._inner.event_records_json())

    async def async_event_records(self) -> dict[str, Any]:
        """Async wrapper for `event_records` using a worker thread."""
        return await asyncio.to_thread(self.event_records)

    def audit(self, memory_id: str, now_unix: int | None = None) -> dict[str, Any]:
        """Return one memory's why trace and related event records."""
        return json.loads(self._inner.audit_json(memory_id, now_unix))

    async def async_audit(self, *args, **kwargs) -> dict[str, Any]:
        """Async wrapper for `audit` using a worker thread."""
        return await asyncio.to_thread(self.audit, *args, **kwargs)

    def consolidate(self, now_unix: int | None = None) -> dict[str, Any]:
        """Run the offline consolidation pass."""
        return json.loads(self._inner.consolidate_json(now_unix))

    async def async_consolidate(self, *args, **kwargs) -> dict[str, Any]:
        """Async wrapper for `consolidate` using a worker thread."""
        return await asyncio.to_thread(self.consolidate, *args, **kwargs)

    def export_records(self) -> list[dict[str, object]]:
        """Return current memory rows as plain Python dictionaries."""
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
        """Return current memory rows as a pandas DataFrame."""
        import pandas as pd

        return pd.DataFrame.from_records(self.export_records())

    def to_arrow(self):
        """Return current memory rows as a PyArrow table."""
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
        max_context_tokens: int | None = None,
        similarity_weight: float = 1.0,
        significance_weight: float = 1.0,
        recency_weight: float = 0.25,
        graph_weight: float = 0.25,
        related_memory_ids_by_anchor: Mapping[str, Sequence[str]] | None = None,
    ) -> RecallStream:
        """Return an iterator over current recall candidates."""
        return self._inner.stream_recall(
            query_vector,
            top_k,
            now_unix,
            raw_query_context,
            include_cold,
            include_instructions,
            max_context_tokens,
            similarity_weight,
            significance_weight,
            recency_weight,
            graph_weight,
            related_memory_ids_by_anchor,
        )

    async def async_stream_recall(self, *args, **kwargs) -> AsyncIterator[RecallCandidate]:
        """Async iterator wrapper for current recall candidates."""
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
        max_context_tokens: int | None = None,
    ) -> list[RecallCandidate]:
        """Recall memories as they were believed at `as_of_unix`."""
        return self._inner.timeline(
            query_vector,
            top_k,
            as_of_unix,
            include_cold,
            include_instructions,
            max_context_tokens,
        )

    async def async_timeline(self, *args, **kwargs) -> list[RecallCandidate]:
        """Async wrapper for `timeline` using a worker thread."""
        return await asyncio.to_thread(self.timeline, *args, **kwargs)

    def stream_timeline(
        self,
        query_vector,
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
        max_context_tokens: int | None = None,
    ) -> RecallStream:
        """Return an iterator over historical recall candidates."""
        return self._inner.stream_timeline(
            query_vector,
            top_k,
            as_of_unix,
            include_cold,
            include_instructions,
            max_context_tokens,
        )

    async def async_stream_timeline(self, *args, **kwargs) -> AsyncIterator[RecallCandidate]:
        """Async iterator wrapper for historical recall candidates."""
        candidates = await self.async_timeline(*args, **kwargs)

        for candidate in candidates:
            yield candidate

    def reinforce(self, memory_id: str, outcome: str = "cited") -> bool:
        """Record a usage outcome for a memory."""
        return self._inner.reinforce(memory_id, outcome)

    async def async_reinforce(self, *args, **kwargs) -> bool:
        """Async wrapper for `reinforce` using a worker thread."""
        return await asyncio.to_thread(self.reinforce, *args, **kwargs)

    def challenge(
        self,
        memory_id: str,
        reason: str,
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]:
        """Challenge a memory and flag it for review."""
        return json.loads(self._inner.challenge_json(memory_id, reason, actor, timestamp_unix))

    async def async_challenge(self, *args, **kwargs) -> dict[str, Any]:
        """Async wrapper for `challenge` using a worker thread."""
        return await asyncio.to_thread(self.challenge, *args, **kwargs)

    def affirm(
        self,
        memory_id: str,
        reason: str = "affirmed",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]:
        """Affirm a memory."""
        return json.loads(self._inner.affirm_json(memory_id, reason, actor, timestamp_unix))

    async def async_affirm(self, *args, **kwargs) -> dict[str, Any]:
        """Async wrapper for `affirm` using a worker thread."""
        return await asyncio.to_thread(self.affirm, *args, **kwargs)

    def correct(
        self,
        memory_id: str,
        proposed_content: str,
        reason: str = "corrected",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]:
        """Correct a memory through quarantine and reconstruction."""
        return json.loads(
            self._inner.correct_json(
                memory_id,
                proposed_content,
                reason,
                actor,
                timestamp_unix,
            )
        )

    async def async_correct(self, *args, **kwargs) -> dict[str, Any]:
        """Async wrapper for `correct` using a worker thread."""
        return await asyncio.to_thread(self.correct, *args, **kwargs)

    def pin(
        self,
        memory_id: str,
        reason: str = "pinned",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]:
        """Pin a memory's credence floor."""
        return json.loads(self._inner.pin_json(memory_id, reason, actor, timestamp_unix))

    async def async_pin(self, *args, **kwargs) -> dict[str, Any]:
        """Async wrapper for `pin` using a worker thread."""
        return await asyncio.to_thread(self.pin, *args, **kwargs)

    def unpin(
        self,
        memory_id: str,
        reason: str = "unpinned",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]:
        """Remove a human credence-floor pin."""
        return json.loads(self._inner.unpin_json(memory_id, reason, actor, timestamp_unix))

    async def async_unpin(self, *args, **kwargs) -> dict[str, Any]:
        """Async wrapper for `unpin` using a worker thread."""
        return await asyncio.to_thread(self.unpin, *args, **kwargs)

    def why(self, memory_id: str, now_unix: int | None = None) -> WhyTrace | None:
        """Explain the current significance, provenance, tier, and currency state."""
        return self._inner.why(memory_id, now_unix)

    async def async_why(self, *args, **kwargs) -> WhyTrace | None:
        """Async wrapper for `why` using a worker thread."""
        return await asyncio.to_thread(self.why, *args, **kwargs)


for _name, _method in vars(Shibahama).items():
    if not _name.startswith("_") and callable(_method):
        setattr(Shibahama, _name, _structured_errors(_method))


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
        """Create a dependency-free LangChain-style memory adapter."""
        self.engine = engine
        self.embed = embed
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self.top_k = top_k

    @property
    def memory_variables(self) -> list[str]:
        """Return the memory variable names exposed to LangChain-style callers."""
        return [self.memory_key]

    def load_memory_variables(self, inputs: Mapping[str, Any]) -> dict[str, str]:
        """Load relevant memory context for a LangChain-style input mapping."""
        query = _mapping_text(inputs, self.input_key)
        candidates = self.engine.recall(self.embed(query), self.top_k)
        history = "\n".join(candidate.item.content for candidate in candidates)

        return {self.memory_key: history}

    async def aload_memory_variables(self, inputs: Mapping[str, Any]) -> dict[str, str]:
        """Async wrapper for `load_memory_variables` using a worker thread."""
        return await asyncio.to_thread(self.load_memory_variables, inputs)

    def save_context(self, inputs: Mapping[str, Any], outputs: Mapping[str, Any]) -> None:
        """Save a LangChain-style input/output turn into Shibahama."""
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
        """Async wrapper for `save_context` using a worker thread."""
        await asyncio.to_thread(self.save_context, inputs, outputs)

    def clear(self) -> None:
        """Compatibility-only no-op; does not delete or invalidate Shibahama memories."""
        return None

    async def aclear(self) -> None:
        """Async compatibility-only no-op; does not delete or invalidate memories."""
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
