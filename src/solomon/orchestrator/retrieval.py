# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.credence.policy import CredenceLedger, RetrievalCandidate
from solomon.currency.contradiction import contradictions_for_item
from solomon.currency.engine import evaluate_currency
from solomon.currency.models import CurrencyState, KnowledgeItem
from solomon.graph.models import DependencyEdge
from solomon.graph.types import DependencyGraphProtocol
from solomon.store.types import KnowledgeStoreProtocol

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_§.-]*")
SEMANTIC_ALIASES = {
    "arrangement": "structure",
    "arrangements": "structure",
    "clause": "section",
    "clauses": "section",
    "law": "regulation",
    "laws": "regulation",
    "provision": "section",
    "provisions": "section",
    "rule": "regulation",
    "rules": "regulation",
    "statute": "regulation",
    "statutes": "regulation",
}


def tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(text)}


def semantic_tokens(text: str) -> set[str]:
    tokens = tokenize(text)
    return tokens | {SEMANTIC_ALIASES[token] for token in tokens if token in SEMANTIC_ALIASES}


class EmbeddingStrategy(SolomonModel):
    name: str = "hashed-token-vector"
    version: str = "1"
    dimensions: int = 256

    @property
    def ref(self) -> str:
        return f"{self.name}:{self.version}"


class IndexedHit(SolomonModel):
    item_id: str
    similarity: float
    embedding_ref: str


class SQLiteRetrievalIndex:
    def __init__(self, path: Path | str, *, strategy: EmbeddingStrategy | None = None) -> None:
        self.path = Path(path)
        self.strategy = strategy or EmbeddingStrategy()
        self._vector_cache: dict[str, tuple[str, list[float]]] = {}
        self._search_cache: dict[tuple[str, int, str], list[IndexedHit]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_index (
                    item_id TEXT PRIMARY KEY,
                    embedding_ref TEXT NOT NULL,
                    tokens_json TEXT NOT NULL,
                    vector_json TEXT NOT NULL DEFAULT '[]',
                    indexed_at TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(retrieval_index)").fetchall()}
            if "vector_json" not in columns:
                self._conn.execute("ALTER TABLE retrieval_index ADD COLUMN vector_json TEXT NOT NULL DEFAULT '[]'")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_ref ON retrieval_index(embedding_ref)")

    def close(self) -> None:
        self._conn.close()

    def upsert_item(self, item: KnowledgeItem, *, indexed_at: datetime | None = None) -> KnowledgeItem:
        from solomon.currency.models import now_utc

        embedding_ref = self.strategy.ref
        tokens = sorted(semantic_tokens(item.content))
        vector = _embed_tokens(tokens, dimensions=self.strategy.dimensions)
        timestamp = indexed_at or now_utc()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO retrieval_index (item_id, embedding_ref, tokens_json, vector_json, indexed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    embedding_ref = excluded.embedding_ref,
                    tokens_json = excluded.tokens_json,
                    vector_json = excluded.vector_json,
                    indexed_at = excluded.indexed_at
                """,
                (item.id, embedding_ref, json.dumps(tokens), json.dumps(vector), timestamp.isoformat()),
            )
        self._vector_cache[item.id] = (embedding_ref, vector)
        self._search_cache.clear()
        return item.model_copy(update={"embedding_ref": embedding_ref})

    def batch_upsert(self, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
        return [self.upsert_item(item) for item in items]

    def embedding_refs(self, item_ids: list[str]) -> dict[str, str]:
        if not item_ids:
            return {}
        placeholders = ",".join("?" for _ in item_ids)
        rows = self._conn.execute(
            f"SELECT item_id, embedding_ref FROM retrieval_index WHERE item_id IN ({placeholders})",  # noqa: S608
            item_ids,
        ).fetchall()
        return {str(row["item_id"]): str(row["embedding_ref"]) for row in rows}

    def search(self, query: str, *, limit: int = 20) -> list[IndexedHit]:
        cache_key = (query, limit, self.strategy.ref)
        if cached_hits := self._search_cache.get(cache_key):
            return list(cached_hits)
        query_tokens = semantic_tokens(query)
        if not query_tokens:
            return []
        query_terms = _nonzero_terms(_embed_tokens(sorted(query_tokens), dimensions=self.strategy.dimensions))
        rows = self._conn.execute(
            "SELECT item_id, embedding_ref, vector_json FROM retrieval_index ORDER BY item_id"
        ).fetchall()
        hits: list[IndexedHit] = []
        for row in rows:
            item_id = str(row["item_id"])
            embedding_ref = str(row["embedding_ref"])
            cached_vector = self._vector_cache.get(item_id)
            if cached_vector is None or cached_vector[0] != embedding_ref:
                cached_vector = (embedding_ref, json.loads(str(row["vector_json"])))
                self._vector_cache[item_id] = cached_vector
            score = _cosine_similarity_terms(query_terms, cached_vector[1])
            if score > 0:
                hits.append(IndexedHit(item_id=item_id, similarity=score, embedding_ref=embedding_ref))
        limited_hits = sorted(hits, key=lambda hit: (hit.similarity, hit.item_id), reverse=True)[:limit]
        self._search_cache[cache_key] = limited_hits
        return list(limited_hits)


class RecallWeights(SolomonModel):
    similarity: float = 0.70
    credence: float = 0.20
    centrality: float = 0.10


class RecallOptions(SolomonModel):
    limit: int = 10
    review_mode: bool = False
    weights: RecallWeights = Field(default_factory=RecallWeights)
    dedupe_near_identical: bool = True
    max_context_tokens: int | None = Field(default=None, ge=1)


class RecallResult(SolomonModel):
    item: KnowledgeItem
    score: float
    similarity: float
    currency_state: CurrencyState
    provenance: dict[str, Any]
    dependencies: list[DependencyEdge]
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    superseded_by: str | None
    last_verified_at: datetime | None
    stale_reasons: list[dict[str, Any]]
    estimated_context_tokens: int


class ReembedReport(SolomonModel):
    embedding_ref: str
    considered_item_ids: list[str]
    reembedded_item_ids: list[str]


class RetrievalIndexProtocol(Protocol):
    strategy: EmbeddingStrategy

    def upsert_item(self, item: KnowledgeItem, *, indexed_at: datetime | None = None) -> KnowledgeItem: ...

    def batch_upsert(self, items: list[KnowledgeItem]) -> list[KnowledgeItem]: ...

    def embedding_refs(self, item_ids: list[str]) -> dict[str, str]: ...

    def search(self, query: str, *, limit: int = 20) -> list[IndexedHit]: ...

    def close(self) -> None: ...


class RetrievalMetricsObserver(Protocol):
    def observe_retrieval(
        self,
        *,
        candidates: int,
        returned: int,
        withheld_by_currency_state: Mapping[CurrencyState, int],
    ) -> None: ...


@dataclass(frozen=True)
class MatterContext:
    matter_id: str | None = None
    client_id: str | None = None


class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        store: KnowledgeStoreProtocol,
        graph: DependencyGraphProtocol,
        index: RetrievalIndexProtocol,
        credence: CredenceLedger | None = None,
    ) -> None:
        self.store = store
        self.graph = graph
        self.index = index
        self.credence = credence or CredenceLedger()
        self.metrics_observer: RetrievalMetricsObserver | None = None

    def index_items(self, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
        indexed = self.index.batch_upsert(items)
        for item in indexed:
            self.store.update_item(item, event_type="knowledge_item_indexed")
        return indexed

    def reembed_stale_items(self, *, item_ids: list[str] | None = None) -> ReembedReport:
        items = self.store.get_many(item_ids)
        considered_ids = [item.id for item in items]
        indexed_refs = self.index.embedding_refs(considered_ids)
        target_ref = self.index.strategy.ref
        stale = [
            item
            for item in items
            if item.embedding_ref != target_ref or indexed_refs.get(item.id) != target_ref
        ]
        self.index_items(stale)
        return ReembedReport(
            embedding_ref=target_ref,
            considered_item_ids=considered_ids,
            reembedded_item_ids=[item.id for item in stale],
        )

    def recall(
        self,
        query: str,
        *,
        matter_context: MatterContext | None = None,
        options: RecallOptions | None = None,
    ) -> list[RecallResult]:
        resolved_options = options or RecallOptions()
        hits = self.index.search(query, limit=max(resolved_options.limit * 4, resolved_options.limit))
        if not hits:
            self._observe_retrieval(candidates=0, results=[], withheld_by_currency_state={})
            return []
        hit_by_id = {hit.item_id: hit for hit in hits}
        item_ids = [hit.item_id for hit in hits]
        matter_id = matter_context.matter_id if matter_context else None
        client_id = matter_context.client_id if matter_context else None
        items = self.store.get_many(item_ids, matter_id=matter_id, client_id=client_id)
        withheld_by_currency_state: dict[CurrencyState, int] = {}
        if not resolved_options.review_mode:
            live_items: list[KnowledgeItem] = []
            for item in items:
                state = evaluate_currency(item).currency_state
                if state is CurrencyState.LIVE:
                    live_items.append(item)
                else:
                    withheld_by_currency_state[state] = withheld_by_currency_state.get(state, 0) + 1
            items = live_items
        items = self._dedupe(items) if resolved_options.dedupe_near_identical else items
        centrality = self.graph.centrality(item.id for item in items)
        candidates = [
            RetrievalCandidate(
                item=item,
                relevance=hit_by_id[item.id].similarity,
                centrality=float(centrality.get(item.id, 0)),
            )
            for item in items
        ]
        ranked = self.credence.rank(candidates)
        results = [
            self._build_result(candidate, hit_by_id[candidate.item.id], resolved_options.weights)
            for candidate in ranked
        ]
        ranked_results = sorted(results, key=lambda result: result.score, reverse=True)
        selected = self._apply_limit_and_budget(ranked_results, resolved_options)
        self._observe_retrieval(
            candidates=len(item_ids),
            results=selected,
            withheld_by_currency_state=withheld_by_currency_state,
        )
        return selected

    def _observe_retrieval(
        self,
        *,
        candidates: int,
        results: list[RecallResult],
        withheld_by_currency_state: Mapping[CurrencyState, int],
    ) -> None:
        if self.metrics_observer is None:
            return
        self.metrics_observer.observe_retrieval(
            candidates=candidates,
            returned=len(results),
            withheld_by_currency_state=withheld_by_currency_state,
        )

    def timeline(
        self,
        query: str,
        *,
        as_of: datetime,
        options: RecallOptions | None = None,
    ) -> list[RecallResult]:
        historical_items = self.store.as_of(as_of)
        query_tokens = tokenize(query)
        hits: dict[str, IndexedHit] = {}
        for item in historical_items:
            item_tokens = tokenize(item.content)
            union = query_tokens | item_tokens
            if union:
                similarity = len(query_tokens & item_tokens) / len(union)
                if similarity > 0:
                    hits[item.id] = IndexedHit(
                        item_id=item.id,
                        similarity=similarity,
                        embedding_ref=item.embedding_ref or self.index.strategy.ref,
                    )
        resolved_options = options or RecallOptions(review_mode=True)
        candidates = [
            RetrievalCandidate(item=item, relevance=hits[item.id].similarity)
            for item in historical_items
            if item.id in hits
        ]
        ranked = self.credence.rank(candidates)
        results = [
            self._build_result(candidate, hits[candidate.item.id], resolved_options.weights)
            for candidate in ranked
        ]
        return self._apply_limit_and_budget(results, resolved_options)

    def _build_result(
        self,
        candidate: RetrievalCandidate,
        hit: IndexedHit,
        weights: RecallWeights,
    ) -> RecallResult:
        item = candidate.item
        evaluation = evaluate_currency(item)
        item = item.model_copy(update={"currency_state": evaluation.currency_state})
        credence_rank = self.credence.policy.tier_rank[item.credence_tier] / max(
            self.credence.policy.tier_rank.values()
        )
        centrality_score = min(candidate.centrality / 10.0, 1.0)
        score = (
            hit.similarity * weights.similarity
            + credence_rank * weights.credence
            + centrality_score * weights.centrality
        )
        return RecallResult(
            item=item,
            score=score,
            similarity=hit.similarity,
            currency_state=evaluation.currency_state,
            provenance=item.provenance.model_dump(mode="json"),
            dependencies=self.graph.get_dependencies(item.id),
            contradictions=[signal.model_dump(mode="json") for signal in contradictions_for_item(item)],
            superseded_by=item.successor_id,
            last_verified_at=item.last_verified_at,
            stale_reasons=[dict(reason) for reason in evaluation.stale_reasons],
            estimated_context_tokens=estimate_context_tokens(item),
        )

    def _apply_limit_and_budget(self, results: list[RecallResult], options: RecallOptions) -> list[RecallResult]:
        selected: list[RecallResult] = []
        used_tokens = 0
        for result in results:
            if len(selected) >= options.limit:
                break
            if options.max_context_tokens is not None:
                next_total = used_tokens + result.estimated_context_tokens
                if next_total > options.max_context_tokens:
                    continue
                used_tokens = next_total
            selected.append(result)
        return selected

    def _dedupe(self, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
        by_content: dict[str, list[KnowledgeItem]] = defaultdict(list)
        for item in items:
            normalized = " ".join(sorted(tokenize(item.content)))
            by_content[normalized].append(item)
        deduped: list[KnowledgeItem] = []
        for group in by_content.values():
            deduped.append(
                sorted(
                    group,
                    key=lambda item: (
                        self.credence.policy.tier_rank[item.credence_tier],
                        item.last_verified_at or item.ingested_at,
                    ),
                    reverse=True,
                )[0]
            )
        return deduped


def estimate_context_tokens(item: KnowledgeItem) -> int:
    return max(1, len(tokenize(item.content)))


def _embed_tokens(tokens: list[str], *, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokens:
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dimensions
        vector[bucket] += 1.0
    magnitude = sum(value * value for value in vector) ** 0.5
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def _nonzero_terms(vector: list[float]) -> list[tuple[int, float]]:
    return [(index, value) for index, value in enumerate(vector) if value]


def _cosine_similarity_terms(left: list[tuple[int, float]], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    max_index = left[-1][0]
    if len(right) <= max_index:
        return 0.0
    return sum(value * right[index] for index, value in left)
