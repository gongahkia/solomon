"""Memory-system adapters used by the benchmark harness."""

from __future__ import annotations

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

    def __init__(
        self,
        dimensions: int = 16,
        *,
        use_significance: bool = True,
        use_reconstruction: bool = True,
        use_graph: bool = True,
    ) -> None:
        try:
            import shibahama
        except ImportError as error:
            raise RuntimeError("install the Shibahama Python binding before benchmarking") from error

        self._module = shibahama
        self._dimensions = dimensions
        self._use_significance = use_significance
        self._use_reconstruction = use_reconstruction
        self._use_graph = use_graph
        self._tmpdir = tempfile.TemporaryDirectory()
        self._engine = None
        self._ids_by_source_ref: dict[str, str] = {}
        self._related_source_refs: dict[str, set[str]] = {}

    def reset(self, case_name: str) -> None:
        path = Path(self._tmpdir.name) / f"{case_name}.redb"
        if path.exists():
            path.unlink()
        self._engine = self._module.Shibahama(str(path), self._dimensions)
        self._ids_by_source_ref = {}
        self._related_source_refs = {}

    def ingest(self, observation: Observation) -> None:
        assert self._engine is not None
        if observation.supersedes_source_ref and self._use_reconstruction:
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

        for _ in range(observation.reinforce_count):
            self._engine.reinforce(item.id, "cited")

        if observation.related_source_refs:
            self._related_source_refs.setdefault(observation.source_ref, set()).update(
                observation.related_source_refs
            )

    def query(self, prompt: str, top_k: int, now_unix: int) -> str:
        assert self._engine is not None
        candidate_pool_size = top_k if self._related_source_refs else max(top_k, 3)
        candidates = self._engine.recall(
            embed_text(prompt, self._dimensions),
            candidate_pool_size,
            now_unix=now_unix,
            raw_query_context=prompt,
            include_cold=True,
            significance_weight=1.0 if self._use_significance else 0.0,
            graph_weight=1.0 if self._use_graph else 0.0,
            related_memory_ids_by_anchor=self._related_memory_ids_by_anchor(),
        )

        return "\n".join(candidate.item.content for candidate in candidates[:top_k])

    def _related_memory_ids_by_anchor(self) -> dict[str, list[str]] | None:
        if not self._use_graph:
            return None

        related_ids_by_anchor = {}
        for anchor_source_ref, related_source_refs in self._related_source_refs.items():
            anchor_id = self._ids_by_source_ref.get(anchor_source_ref)
            if anchor_id is None:
                continue
            related_ids = [
                related_id
                for related_source_ref in sorted(related_source_refs)
                if (related_id := self._ids_by_source_ref.get(related_source_ref)) is not None
            ]
            if related_ids:
                related_ids_by_anchor[anchor_id] = related_ids

        return related_ids_by_anchor or None


class ShibahamaNoSignificanceAdapter(ShibahamaAdapter):
    """Shibahama adapter with significance removed from recall ranking."""

    name = "shibahama-no-significance"

    def __init__(self) -> None:
        super().__init__(use_significance=False)


class ShibahamaNoReconstructionAdapter(ShibahamaAdapter):
    """Shibahama adapter with supersession invalidation disabled."""

    name = "shibahama-no-reconstruction"

    def __init__(self) -> None:
        super().__init__(use_reconstruction=False)


class ShibahamaNoGraphAdapter(ShibahamaAdapter):
    """Shibahama adapter with graph-related recall expansion disabled."""

    name = "shibahama-no-graph"

    def __init__(self) -> None:
        super().__init__(use_graph=False)


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


@dataclass(frozen=True)
class AdapterFactory:
    """Named adapter constructor."""

    name: str
    build: type[MemoryAdapter]


ADAPTERS: dict[str, type[MemoryAdapter]] = {
    "shibahama": ShibahamaAdapter,
    "shibahama-no-significance": ShibahamaNoSignificanceAdapter,
    "shibahama-no-reconstruction": ShibahamaNoReconstructionAdapter,
    "shibahama-no-graph": ShibahamaNoGraphAdapter,
    "warehouse": WarehouseAdapter,
}
