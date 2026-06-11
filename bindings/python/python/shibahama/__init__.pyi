# SPDX-License-Identifier: MIT

from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from typing import Any, Literal

SourceKind = Literal["user", "agent", "file", "web", "tool"]
MemoryKind = Literal["fact", "instruction"]
AccessOutcome = Literal["surfaced", "led_somewhere", "cited", "ignored", "contradicted"]
Tier = Literal["cold", "warm", "hot"]
Credence = Literal[
    "unverified",
    "model_inferred",
    "verified_source",
    "firm_authoritative",
]
Currency = Literal["current", "not_yet_valid", "invalidated"]

__version__: str

def version() -> str: ...

class Provenance:
    source_kind: SourceKind
    source_ref: str | None
    ingested_by: str

class MemoryItem:
    id: str
    content: str
    kind: MemoryKind
    provenance: Provenance
    tier: Tier
    credence: Credence
    significance: float
    credence_floor: Tier
    valid_from_unix: int
    valid_to_unix: int | None
    ingested_at_unix: int

class RecallCandidate:
    id: str
    item: MemoryItem
    kind: MemoryKind
    provenance: Provenance
    tier: Tier
    currency: Currency
    load_bearing_possibly_stale: bool
    cold_tier_retrieval: bool
    vector_distance: float
    similarity_score: float
    significance_score: float
    recency_score: float
    graph_score: float
    source: str
    rank_score: float
    read_safety_findings: list[str]

class SignificanceBreakdown:
    base_score: float
    decay_multiplier: float
    decayed_base: float
    reinforcement: float
    outcome_bonus: float
    contradiction_penalty: float
    graph_centrality: float
    final_score: float

class WhyTrace:
    item: MemoryItem
    significance: SignificanceBreakdown
    provenance: Provenance
    tier_current: Tier
    tier_credence: Credence
    tier_credence_floor: Tier
    currency_state: Currency
    currency_as_of_unix: int
    valid_from_unix: int
    valid_to_unix: int | None
    ingested_at_unix: int
    audit_trail: list[str]

class RecallStream(Iterator[RecallCandidate]):
    def remaining(self) -> int: ...
    def __iter__(self) -> RecallStream: ...
    def __next__(self) -> RecallCandidate: ...

class Shibahama:
    def __init__(self, path: str, dimensions: int, capacity: int = 1024) -> None: ...
    def write(
        self,
        content: str,
        vector: Sequence[float] | None = None,
        source_kind: SourceKind = "user",
        source_ref: str | None = None,
        ingested_by: str = "python",
        valid_from_unix: int | None = None,
        ingested_at_unix: int | None = None,
        kind: MemoryKind = "fact",
        index_name: str = "default",
        model: str = "unknown",
        model_version: str = "unknown",
    ) -> MemoryItem: ...
    async def async_write(
        self,
        content: str,
        vector: Sequence[float] | None = None,
        source_kind: SourceKind = "user",
        source_ref: str | None = None,
        ingested_by: str = "python",
        valid_from_unix: int | None = None,
        ingested_at_unix: int | None = None,
        kind: MemoryKind = "fact",
        index_name: str = "default",
        model: str = "unknown",
        model_version: str = "unknown",
    ) -> MemoryItem: ...
    def recall(
        self,
        query_vector: Sequence[float],
        top_k: int,
        now_unix: int | None = None,
        raw_query_context: str | None = None,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> list[RecallCandidate]: ...
    async def async_recall(
        self,
        query_vector: Sequence[float],
        top_k: int,
        now_unix: int | None = None,
        raw_query_context: str | None = None,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> list[RecallCandidate]: ...
    def memory_items(self) -> list[MemoryItem]: ...
    def export_records(self) -> list[dict[str, object]]: ...
    def to_pandas(self) -> Any: ...
    def to_arrow(self) -> Any: ...
    def stream_recall(
        self,
        query_vector: Sequence[float],
        top_k: int,
        now_unix: int | None = None,
        raw_query_context: str | None = None,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> RecallStream: ...
    async def async_stream_recall(
        self,
        query_vector: Sequence[float],
        top_k: int,
        now_unix: int | None = None,
        raw_query_context: str | None = None,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> AsyncIterator[RecallCandidate]: ...
    def timeline(
        self,
        query_vector: Sequence[float],
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> list[RecallCandidate]: ...
    async def async_timeline(
        self,
        query_vector: Sequence[float],
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> list[RecallCandidate]: ...
    def stream_timeline(
        self,
        query_vector: Sequence[float],
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> RecallStream: ...
    async def async_stream_timeline(
        self,
        query_vector: Sequence[float],
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
    ) -> AsyncIterator[RecallCandidate]: ...
    def reinforce(self, memory_id: str, outcome: AccessOutcome = "cited") -> bool: ...
    async def async_reinforce(
        self, memory_id: str, outcome: AccessOutcome = "cited"
    ) -> bool: ...
    def why(self, memory_id: str, now_unix: int | None = None) -> WhyTrace | None: ...
    async def async_why(
        self, memory_id: str, now_unix: int | None = None
    ) -> WhyTrace | None: ...

class LangChainMemory:
    engine: Shibahama
    embed: Callable[[str], Sequence[float]]
    memory_key: str
    input_key: str
    output_key: str
    top_k: int
    def __init__(
        self,
        engine: Shibahama,
        embed: Callable[[str], Sequence[float]],
        memory_key: str = "history",
        input_key: str = "input",
        output_key: str = "output",
        top_k: int = 5,
    ) -> None: ...
    @property
    def memory_variables(self) -> list[str]: ...
    def load_memory_variables(self, inputs: Mapping[str, Any]) -> dict[str, str]: ...
    async def aload_memory_variables(self, inputs: Mapping[str, Any]) -> dict[str, str]: ...
    def save_context(
        self, inputs: Mapping[str, Any], outputs: Mapping[str, Any]
    ) -> None: ...
    async def asave_context(
        self, inputs: Mapping[str, Any], outputs: Mapping[str, Any]
    ) -> None: ...
    def clear(self) -> None: ...
    async def aclear(self) -> None: ...
