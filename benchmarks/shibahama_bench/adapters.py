"""Memory-system adapters used by the benchmark harness."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .embeddings import embed_text
from .tasks import Observation


class MemoryAdapter(Protocol):
    """Common interface for benchmarked memory systems."""

    name: str

    def reset(self, case_name: str) -> None:
        """Reset system state for a benchmark case."""

    def ingest(self, observation: Observation) -> None:
        """Store one observation."""

    def query(self, prompt: str, top_k: int, now_unix: int) -> str:
        """Return retrieved memory text for a query."""


class ShibahamaAdapter:
    """Adapter for the in-process Shibahama Python binding."""

    name = "shibahama"

    def __init__(self, dimensions: int = 16) -> None:
        try:
            import shibahama
        except ImportError as error:
            raise RuntimeError("install the Shibahama Python binding before benchmarking") from error

        self._module = shibahama
        self._dimensions = dimensions
        self._tmpdir = tempfile.TemporaryDirectory()
        self._engine = None
        self._ids_by_source_ref: dict[str, str] = {}

    def reset(self, case_name: str) -> None:
        path = Path(self._tmpdir.name) / f"{case_name}.redb"
        if path.exists():
            path.unlink()
        self._engine = self._module.Shibahama(str(path), self._dimensions)
        self._ids_by_source_ref = {}

    def ingest(self, observation: Observation) -> None:
        assert self._engine is not None
        if observation.supersedes_source_ref:
            superseded_id = self._ids_by_source_ref.get(observation.supersedes_source_ref)
            if superseded_id:
                self._engine.invalidate(superseded_id, observation.valid_from_unix)

        item = self._engine.write(
            observation.content,
            vector=embed_text(observation.content, self._dimensions),
            source_kind="user",
            source_ref=observation.source_ref,
            ingested_by="benchmark",
            valid_from_unix=observation.valid_from_unix,
            ingested_at_unix=observation.valid_from_unix,
        )
        self._ids_by_source_ref[observation.source_ref] = item.id

    def query(self, prompt: str, top_k: int, now_unix: int) -> str:
        assert self._engine is not None
        candidates = self._engine.recall(
            embed_text(prompt, self._dimensions),
            top_k,
            now_unix=now_unix,
            raw_query_context=prompt,
            include_cold=True,
        )

        return "\n".join(candidate.item.content for candidate in candidates)


class WarehouseAdapter:
    """Append-only keyword baseline that intentionally has no currency model."""

    name = "warehouse"

    def __init__(self) -> None:
        self._rows: list[Observation] = []

    def reset(self, case_name: str) -> None:
        self._rows = []

    def ingest(self, observation: Observation) -> None:
        self._rows.append(observation)

    def query(self, prompt: str, top_k: int, now_unix: int) -> str:
        prompt_terms = set(prompt.casefold().replace("/", " ").replace("_", " ").split())
        scored = []

        for index, row in enumerate(self._rows):
            row_terms = set(row.content.casefold().replace("/", " ").replace("_", " ").split())
            overlap = len(prompt_terms & row_terms)
            scored.append((overlap, -index, row.content))

        scored.sort(reverse=True)

        return "\n".join(content for overlap, _, content in scored[:top_k] if overlap > 0)


class Mem0Adapter:
    """Adapter for the Mem0 OSS Python SDK.

    This follows the public SDK shape documented by Mem0: `Memory().add(...)`
    and `Memory().search(..., filters={"user_id": ...})`.
    """

    name = "mem0"

    def __init__(self) -> None:
        try:
            from mem0 import Memory
        except ImportError as error:
            raise RuntimeError("install mem0ai and configure its model/vector backend") from error

        self._memory_cls = Memory
        self._memory = None
        self._user_id = "shibahama-bench"

    def reset(self, case_name: str) -> None:
        self._memory = self._memory_cls()
        self._user_id = f"shibahama-bench-{case_name}"

    def ingest(self, observation: Observation) -> None:
        assert self._memory is not None
        messages = [{"role": "user", "content": observation.content}]
        self._memory.add(messages, user_id=self._user_id)

    def query(self, prompt: str, top_k: int, now_unix: int) -> str:
        assert self._memory is not None
        result = self._memory.search(prompt, filters={"user_id": self._user_id}, limit=top_k)
        rows = result.get("results", result if isinstance(result, list) else [])

        return "\n".join(str(row.get("memory", row)) for row in rows[:top_k])


class ZepAdapter:
    """Adapter for Zep Cloud's current thread context API."""

    name = "zep"

    def __init__(self) -> None:
        api_key = os.environ.get("ZEP_API_KEY")
        if not api_key:
            raise RuntimeError("set ZEP_API_KEY before running the Zep adapter")

        try:
            from zep_cloud.client import Zep
            from zep_cloud.types import Message
        except ImportError:
            try:
                from zep_cloud import Zep, Message
            except ImportError as error:
                raise RuntimeError("install zep-cloud before running the Zep adapter") from error

        self._client = Zep(api_key=api_key)
        self._message_cls = Message
        self._user_id = "shibahama-bench"
        self._thread_id = "shibahama-bench"

    def reset(self, case_name: str) -> None:
        self._user_id = f"shibahama-bench-{case_name}"
        self._thread_id = f"shibahama-bench-{case_name}"
        self._client.user.add(user_id=self._user_id)
        self._client.thread.create(thread_id=self._thread_id, user_id=self._user_id)

    def ingest(self, observation: Observation) -> None:
        message = self._message_cls(
            role="user",
            content=observation.content,
            name="benchmark",
        )
        self._client.thread.add_messages(thread_id=self._thread_id, messages=[message])

    def query(self, prompt: str, top_k: int, now_unix: int) -> str:
        message = self._message_cls(role="user", content=prompt, name="benchmark")
        self._client.thread.add_messages(thread_id=self._thread_id, messages=[message])
        context = self._client.thread.get_user_context(thread_id=self._thread_id)

        return str(context.context)


@dataclass(frozen=True)
class AdapterFactory:
    """Named adapter constructor."""

    name: str
    build: type[MemoryAdapter]


ADAPTERS: dict[str, type[MemoryAdapter]] = {
    "shibahama": ShibahamaAdapter,
    "warehouse": WarehouseAdapter,
    "mem0": Mem0Adapter,
    "zep": ZepAdapter,
}
