# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


def test_sqlite_wal_handles_characterized_multi_connection_writes(tmp_path: Path) -> None:
    db = tmp_path / "solomon.sqlite3"
    writer_count = 4
    writes_per_writer = 25

    def write_shard(shard: int) -> None:
        store = SQLiteKnowledgeStore(db)
        try:
            for offset in range(writes_per_writer):
                item_id = f"writer-{shard}-item-{offset}"
                store.write_item(
                    KnowledgeItem(
                        id=item_id,
                        kind=KnowledgeKind.NOTE,
                        content=f"concurrent write {shard} {offset}",
                        provenance=Provenance(source_kind=SourceKind.ASSOCIATE, source_ref=item_id),
                    )
                )
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=writer_count) as executor:
        list(executor.map(write_shard, range(writer_count)))

    store = SQLiteKnowledgeStore(db)
    try:
        items = store.get_many()
        assert len(items) == writer_count * writes_per_writer
        assert int(store.pragma("busy_timeout")) >= 5000
        assert str(store.pragma("journal_mode")).lower() == "wal"
    finally:
        store.close()
