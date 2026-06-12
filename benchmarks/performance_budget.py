# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from solomon.credence.policy import CredenceLedger
from solomon.currency.models import (
    CredenceTier,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceKind,
    VerifiedState,
    now_utc,
)
from solomon.graph.store import GraphStore
from solomon.orchestrator.retrieval import RecallOptions, RetrievalOrchestrator, SQLiteRetrievalIndex
from solomon.performance import LatencyBudget, assert_recall_budget, measure_latency
from solomon.store.sqlite import SQLiteKnowledgeStore

CORPUS_SIZE = int(os.environ.get("SOLOMON_BENCHMARK_CORPUS_SIZE", "750"))
SAMPLES = int(os.environ.get("SOLOMON_BENCHMARK_SAMPLES", "25"))
QUERY = "regulation r structure target clause"


def _budget_from_env() -> LatencyBudget:
    return LatencyBudget(
        recall_p50_ms=float(os.environ.get("SOLOMON_RECALL_P50_MS", "75")),
        recall_p95_ms=float(os.environ.get("SOLOMON_RECALL_P95_MS", "200")),
    )


def _build_retrieval(tmp: Path) -> RetrievalOrchestrator:
    db = tmp / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(db)
    graph = GraphStore(db)
    index = SQLiteRetrievalIndex(db)
    retrieval = RetrievalOrchestrator(store=store, graph=graph, index=index, credence=CredenceLedger())

    items: list[KnowledgeItem] = []
    verified_at = now_utc()
    for item_number in range(CORPUS_SIZE):
        topic = "target clause" if item_number % 17 == 0 else f"background topic {item_number % 31}"
        item = KnowledgeItem(
            id=f"bench-{item_number:04d}",
            kind=KnowledgeKind.POSITION,
            content=f"memo {item_number} covers regulation r structure {topic}",
            provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref=f"bench-{item_number:04d}"),
            credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
            verified_state=VerifiedState.VERIFIED,
            last_verified_at=verified_at,
            verified_by="benchmark-fixture",
        )
        store.write_item(item)
        items.append(item)
    retrieval.index_items(items)
    return retrieval


def main() -> int:
    budget = _budget_from_env()
    with tempfile.TemporaryDirectory(prefix="solomon-benchmark-") as raw_tmp:
        retrieval = _build_retrieval(Path(raw_tmp))
        options = RecallOptions(limit=10)

        warmup = retrieval.recall(QUERY, options=options)
        if not warmup:
            raise SystemExit("latency benchmark failed: warmup recall returned no results")

        measurement = measure_latency(lambda: retrieval.recall(QUERY, options=options), samples=SAMPLES)
        passed = assert_recall_budget(measurement, budget)
        payload = {
            "benchmark": "local_recall_latency",
            "corpus_size": CORPUS_SIZE,
            "samples": SAMPLES,
            "query": QUERY,
            "measurement": measurement.model_dump(mode="json"),
            "budget": budget.model_dump(mode="json"),
            "passed": passed,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        if not passed:
            raise SystemExit("latency budget failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
