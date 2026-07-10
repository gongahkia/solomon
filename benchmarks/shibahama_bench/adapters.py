"""Memory-system adapters used by the benchmark harness."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .embeddings import embed_text
from .tasks import Observation


SHIBAHAMA_DIMENSIONS = 16
MEM0_EMBEDDER_PROVIDER = "fastembed"
MEM0_EMBEDDER_MODEL = "deterministic-blake2b"
MEM0_EMBEDDING_DIMENSIONS = SHIBAHAMA_DIMENSIONS


def safe_collection_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return name[:48] or "case"


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
    model = "shibahama-python-binding+deterministic-blake2b-embeddings"
    tokenizer = "whitespace"

    def __init__(
        self,
        dimensions: int = SHIBAHAMA_DIMENSIONS,
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
        self.config = {
            "dimensions": dimensions,
            "embedding_model": "deterministic-blake2b",
            "significance_weight": 1.0 if use_significance else 0.0,
            "graph_weight": 1.0 if use_graph else 0.0,
            "supersession": "invalidate superseded source_ref before writing current observation"
            if use_reconstruction
            else "disabled",
        }
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
    model = "shibahama-python-binding+deterministic-blake2b-embeddings"
    tokenizer = "whitespace"

    def __init__(self) -> None:
        super().__init__(use_significance=False)


class ShibahamaNoReconstructionAdapter(ShibahamaAdapter):
    """Shibahama adapter with supersession invalidation disabled."""

    name = "shibahama-no-reconstruction"
    model = "shibahama-python-binding+deterministic-blake2b-embeddings"
    tokenizer = "whitespace"

    def __init__(self) -> None:
        super().__init__(use_reconstruction=False)


class ShibahamaNoGraphAdapter(ShibahamaAdapter):
    """Shibahama adapter with graph-related recall expansion disabled."""

    name = "shibahama-no-graph"
    model = "shibahama-python-binding+deterministic-blake2b-embeddings"
    tokenizer = "whitespace"

    def __init__(self) -> None:
        super().__init__(use_graph=False)


class WarehouseAdapter:
    """Append-only keyword baseline that intentionally has no currency model."""

    name = "warehouse"
    model = "append-only-keyword-overlap"
    tokenizer = "whitespace"
    config = {"ranking": "keyword overlap, append-order tie break, no invalidation"}

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


class FullContextAdapter:
    """Returns every observation available at query time."""

    name = "full-context"
    model = "all-observations-by-valid-time"
    tokenizer = "whitespace"
    config = {"ranking": "all observations with valid_from_unix <= query time, newest first"}

    def __init__(self) -> None:
        self._rows: list[Observation] = []

    def reset(self, case_name: str) -> None:
        self._rows = []

    def ingest(self, observation: Observation) -> None:
        self._rows.append(observation)

    def query(self, prompt: str, top_k: int, now_unix: int) -> str:
        _ = prompt, top_k
        rows = [
            row
            for row in sorted(self._rows, key=lambda row: row.valid_from_unix, reverse=True)
            if row.valid_from_unix <= now_unix
        ]

        return "\n".join(row.content for row in rows)


class Mem0DeterministicEmbeddings:
    """Mem0 embedding adapter using Shibahama's deterministic local vectors."""

    def __init__(self, config: object | None = None) -> None:
        self.config = config

    def embed(self, text: str, memory_action: str | None = None) -> list[float]:
        _ = memory_action
        return embed_text(text, MEM0_EMBEDDING_DIMENSIONS)


class Mem0OssExactAdapter:
    """Mem0 OSS exact-event retrieval baseline."""

    name = "mem0-oss-exact"
    model = f"mem0ai+fastembed:{MEM0_EMBEDDER_MODEL}"
    tokenizer = "whitespace"

    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["MEM0_DIR"] = str(Path(self._tmpdir.name) / "mem0-home")
        os.environ["MEM0_TELEMETRY"] = "False"
        from mem0 import Memory
        from mem0.utils.factory import EmbedderFactory
        import mem0

        EmbedderFactory.provider_to_class[MEM0_EMBEDDER_PROVIDER] = (
            "shibahama_bench.adapters.Mem0DeterministicEmbeddings"
        )
        self._memory_cls = Memory
        self._memory = None
        self._case_name = ""
        self.config = {
            "mem0_version": getattr(mem0, "__version__", "unknown"),
            "add_infer": False,
            "embedder": (
                "Mem0 EmbedderFactory fastembed provider routed to "
                "shibahama_bench.adapters.Mem0DeterministicEmbeddings"
            ),
            "embedder_model": MEM0_EMBEDDER_MODEL,
            "vector_store": "qdrant-local",
            "collection": "one local collection per benchmark case",
            "embedding_dimensions": MEM0_EMBEDDING_DIMENSIONS,
            "llm": "openai client initialized with dummy key; not called because infer=False",
        }

    def reset(self, case_name: str) -> None:
        self._case_name = case_name
        collection_name = f"phase_c_mem0_{safe_collection_name(case_name)}"
        path = Path(self._tmpdir.name) / "mem0" / safe_collection_name(case_name)
        path.mkdir(parents=True, exist_ok=True)
        config = {
            "version": "v1.1",
            "embedder": {
                "provider": MEM0_EMBEDDER_PROVIDER,
                "config": {
                    "model": MEM0_EMBEDDER_MODEL,
                    "embedding_dims": MEM0_EMBEDDING_DIMENSIONS,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": collection_name,
                    "embedding_model_dims": MEM0_EMBEDDING_DIMENSIONS,
                    "path": str(path / "qdrant"),
                },
            },
            "llm": {"provider": "openai", "config": {"api_key": "dummy", "model": "gpt-5-mini"}},
            "history_db_path": str(path / "history.db"),
        }
        self._memory = self._memory_cls.from_config(config)

    def ingest(self, observation: Observation) -> None:
        assert self._memory is not None
        self._memory.add(
            observation.content,
            user_id=self._case_name,
            metadata={"source_ref": observation.source_ref},
            infer=False,
        )

    def query(self, prompt: str, top_k: int, now_unix: int) -> str:
        _ = now_unix
        assert self._memory is not None
        result = self._memory.search(prompt, filters={"user_id": self._case_name}, top_k=top_k)
        rows = result.get("results", result if isinstance(result, list) else [])

        return "\n".join(str(row.get("memory", "")) for row in rows)


@dataclass(frozen=True)
class AdapterMetadata:
    """Reproducibility metadata for a benchmark adapter."""

    name: str
    is_external: bool
    result_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterFactory:
    """Named adapter constructor."""

    metadata: AdapterMetadata
    build: type[MemoryAdapter]


ADAPTERS: dict[str, type[MemoryAdapter]] = {
    "shibahama": ShibahamaAdapter,
    "shibahama-no-significance": ShibahamaNoSignificanceAdapter,
    "shibahama-no-reconstruction": ShibahamaNoReconstructionAdapter,
    "shibahama-no-graph": ShibahamaNoGraphAdapter,
    "warehouse": WarehouseAdapter,
    "full-context": FullContextAdapter,
    "mem0-oss-exact": Mem0OssExactAdapter,
}

ADAPTER_METADATA: dict[str, AdapterMetadata] = {
    "shibahama": AdapterMetadata(name="shibahama", is_external=False),
    "shibahama-no-significance": AdapterMetadata(
        name="shibahama-no-significance",
        is_external=False,
    ),
    "shibahama-no-reconstruction": AdapterMetadata(
        name="shibahama-no-reconstruction",
        is_external=False,
    ),
    "shibahama-no-graph": AdapterMetadata(name="shibahama-no-graph", is_external=False),
    "warehouse": AdapterMetadata(name="warehouse", is_external=False),
    "full-context": AdapterMetadata(name="full-context", is_external=False),
    "mem0-oss-exact": AdapterMetadata(
        name="mem0-oss-exact",
        is_external=True,
        result_artifacts=("continuity/mem0-oss-exact.json", "continuity/mem0-oss-exact.md"),
    ),
}


def adapter_reproducibility(adapter: MemoryAdapter) -> dict[str, object]:
    """Return stable manifest metadata for a benchmark adapter instance."""

    return {
        "model": getattr(adapter, "model", "unknown"),
        "tokenizer": getattr(adapter, "tokenizer", "whitespace"),
        "config": getattr(adapter, "config", {}),
    }

def validate_adapter_registry(results_root: Path | None = None) -> None:
    """Validate that every adapter is registered and external adapters have artifacts."""

    missing_metadata = sorted(set(ADAPTERS) - set(ADAPTER_METADATA))
    if missing_metadata:
        names = ", ".join(missing_metadata)
        raise RuntimeError(f"benchmark adapters missing reproducibility metadata: {names}")

    root = results_root or Path(__file__).resolve().parents[1] / "results"
    missing_artifacts = []
    for metadata in ADAPTER_METADATA.values():
        if not metadata.is_external:
            continue
        if not metadata.result_artifacts:
            missing_artifacts.append(metadata.name)
            continue
        if any(not (root / artifact).exists() for artifact in metadata.result_artifacts):
            missing_artifacts.append(metadata.name)

    if missing_artifacts:
        names = ", ".join(sorted(missing_artifacts))
        raise RuntimeError(
            "external benchmark adapters require checked-in reproducible result artifacts: "
            f"{names}"
        )


validate_adapter_registry()
