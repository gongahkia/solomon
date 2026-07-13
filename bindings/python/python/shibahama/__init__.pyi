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

class ShibahamaError(RuntimeError):
    code: str
    severity: Literal["recoverable", "fatal"]
    retryable: bool

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
    def invalidate(self, memory_id: str, valid_to_unix: int) -> bool: ...
    async def async_invalidate(self, memory_id: str, valid_to_unix: int) -> bool: ...
    def recall(
        self,
        query_vector: Sequence[float],
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
    ) -> list[RecallCandidate]: ...
    async def async_recall(
        self,
        query_vector: Sequence[float],
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
    ) -> list[RecallCandidate]: ...
    def memory_items(self) -> list[MemoryItem]: ...
    def event_records(self) -> dict[str, Any]: ...
    async def async_event_records(self) -> dict[str, Any]: ...
    def audit(self, memory_id: str, now_unix: int | None = None) -> dict[str, Any]: ...
    async def async_audit(
        self, memory_id: str, now_unix: int | None = None
    ) -> dict[str, Any]: ...
    def consolidate(self, now_unix: int | None = None) -> dict[str, Any]: ...
    async def async_consolidate(self, now_unix: int | None = None) -> dict[str, Any]: ...
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
        max_context_tokens: int | None = None,
        similarity_weight: float = 1.0,
        significance_weight: float = 1.0,
        recency_weight: float = 0.25,
        graph_weight: float = 0.25,
        related_memory_ids_by_anchor: Mapping[str, Sequence[str]] | None = None,
    ) -> RecallStream: ...
    async def async_stream_recall(
        self,
        query_vector: Sequence[float],
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
    ) -> AsyncIterator[RecallCandidate]: ...
    def timeline(
        self,
        query_vector: Sequence[float],
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
        max_context_tokens: int | None = None,
    ) -> list[RecallCandidate]: ...
    async def async_timeline(
        self,
        query_vector: Sequence[float],
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
        max_context_tokens: int | None = None,
    ) -> list[RecallCandidate]: ...
    def stream_timeline(
        self,
        query_vector: Sequence[float],
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
        max_context_tokens: int | None = None,
    ) -> RecallStream: ...
    async def async_stream_timeline(
        self,
        query_vector: Sequence[float],
        top_k: int,
        as_of_unix: int,
        include_cold: bool = False,
        include_instructions: bool = False,
        max_context_tokens: int | None = None,
    ) -> AsyncIterator[RecallCandidate]: ...
    def reinforce(self, memory_id: str, outcome: AccessOutcome = "cited") -> bool: ...
    async def async_reinforce(
        self, memory_id: str, outcome: AccessOutcome = "cited"
    ) -> bool: ...
    def challenge(
        self,
        memory_id: str,
        reason: str,
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    async def async_challenge(
        self,
        memory_id: str,
        reason: str,
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    def affirm(
        self,
        memory_id: str,
        reason: str = "affirmed",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    async def async_affirm(
        self,
        memory_id: str,
        reason: str = "affirmed",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    def correct(
        self,
        memory_id: str,
        proposed_content: str,
        reason: str = "corrected",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    async def async_correct(
        self,
        memory_id: str,
        proposed_content: str,
        reason: str = "corrected",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    def pin(
        self,
        memory_id: str,
        reason: str = "pinned",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    async def async_pin(
        self,
        memory_id: str,
        reason: str = "pinned",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    def unpin(
        self,
        memory_id: str,
        reason: str = "unpinned",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
    async def async_unpin(
        self,
        memory_id: str,
        reason: str = "unpinned",
        actor: str = "python",
        timestamp_unix: int | None = None,
    ) -> dict[str, Any]: ...
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
def capabilities() -> dict[str, object]: ...
