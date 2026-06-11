# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.credence.policy import CredenceLedger, RetrievalCandidate
from solomon.currency.engine import evaluate_currency
from solomon.currency.models import CurrencyState, KnowledgeItem
from solomon.graph.models import DependencyEdge
from solomon.graph.store import GraphStore
from solomon.store.sqlite import SQLiteKnowledgeStore

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_§.-]*")


def tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(text)}


class EmbeddingStrategy(SolomonModel):
    name: str = "lexical-token-set"
    version: str = "1"

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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
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
                    indexed_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_ref ON retrieval_index(embedding_ref)")

    def upsert_item(self, item: KnowledgeItem, *, indexed_at: datetime | None = None) -> KnowledgeItem:
        from solomon.currency.models import now_utc

        embedding_ref = self.strategy.ref
        tokens = sorted(tokenize(item.content))
        timestamp = indexed_at or now_utc()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO retrieval_index (item_id, embedding_ref, tokens_json, indexed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    embedding_ref = excluded.embedding_ref,
                    tokens_json = excluded.tokens_json,
                    indexed_at = excluded.indexed_at
                """,
                (item.id, embedding_ref, json.dumps(tokens), timestamp.isoformat()),
            )
        return item.model_copy(update={"embedding_ref": embedding_ref})

    def batch_upsert(self, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
        return [self.upsert_item(item) for item in items]

    def search(self, query: str, *, limit: int = 20) -> list[IndexedHit]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        rows = self._conn.execute(
            "SELECT item_id, embedding_ref, tokens_json FROM retrieval_index ORDER BY item_id"
        ).fetchall()
        hits: list[IndexedHit] = []
        for row in rows:
            tokens = set(json.loads(str(row["tokens_json"])))
            union = query_tokens | tokens
            if not union:
                continue
            score = len(query_tokens & tokens) / len(union)
            if score > 0:
                hits.append(
                    IndexedHit(item_id=str(row["item_id"]), similarity=score, embedding_ref=str(row["embedding_ref"]))
                )
        return sorted(hits, key=lambda hit: (hit.similarity, hit.item_id), reverse=True)[:limit]


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
    superseded_by: str | None
    last_verified_at: datetime | None
    stale_reasons: list[dict[str, Any]]
    estimated_context_tokens: int


@dataclass(frozen=True)
class MatterContext:
    matter_id: str | None = None
    client_id: str | None = None


class RetrievalOrchestrator:
    def __init__(
        self,
        *,
        store: SQLiteKnowledgeStore,
        graph: GraphStore,
        index: SQLiteRetrievalIndex,
        credence: CredenceLedger | None = None,
    ) -> None:
        self.store = store
        self.graph = graph
        self.index = index
        self.credence = credence or CredenceLedger()

    def index_items(self, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
        indexed = self.index.batch_upsert(items)
        for item in indexed:
            self.store.update_item(item, event_type="knowledge_item_indexed")
        return indexed

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
            return []
        hit_by_id = {hit.item_id: hit for hit in hits}
        states = None if resolved_options.review_mode else {CurrencyState.LIVE}
        item_ids = [hit.item_id for hit in hits]
        matter_id = matter_context.matter_id if matter_context else None
        client_id = matter_context.client_id if matter_context else None
        items = self.store.get_many(item_ids, include_states=states, matter_id=matter_id, client_id=client_id)
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
        return self._apply_limit_and_budget(ranked_results, resolved_options)

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
