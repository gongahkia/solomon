# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from solomon.currency.models import KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.performance import LatencyBudget, assert_recall_budget, estimate_local_memory_bytes, measure_latency
from solomon.store.sqlite import SQLiteKnowledgeStore


def test_store_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    store = SQLiteKnowledgeStore(tmp_path / "solomon.sqlite3")

    assert str(store.pragma("journal_mode")).lower() == "wal"
    assert int(store.pragma("busy_timeout")) >= 5000


def test_latency_and_memory_budget_helpers() -> None:
    measurement = measure_latency(lambda: sum(range(10)), samples=3)
    item = KnowledgeItem(
        kind=KnowledgeKind.NOTE,
        content="small",
        provenance=Provenance(source_kind=SourceKind.ASSOCIATE, source_ref="note"),
    )

    assert assert_recall_budget(measurement, LatencyBudget(recall_p50_ms=1000, recall_p95_ms=1000)) is True
    assert estimate_local_memory_bytes([item]) > 0

