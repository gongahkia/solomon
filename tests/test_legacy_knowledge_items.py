# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from solomon.currency.models import KnowledgeContentRole, KnowledgeItem, is_v01_knowledge_item_payload
from solomon.store.postgres.serialization import item_from_json
from solomon.store.sqlite import SQLiteKnowledgeStore


def _v01_payload() -> dict[str, object]:
    timestamp = datetime(2026, 6, 11, tzinfo=timezone.utc).isoformat()
    return {
        "id": "legacy-item-1",
        "schema_version": 1,
        "kind": "position",
        "content": "Legacy position under Regulation R section 12.",
        "provenance": {
            "source_kind": "partner",
            "source_ref": "legacy-memo",
            "kaypoh_review_classification": "SAFE",
            "kaypoh_findings": [{"kind": "client_reference"}],
        },
        "valid_from": timestamp,
        "ingested_at": timestamp,
        "credence_tier": "FirmAuthoritative",
        "currency_state": "Live",
        "verified_state": "Verified",
        "last_verified_at": timestamp,
        "metadata": {},
    }


def test_v01_knowledge_item_payload_migrates_to_claim_compatible_shape_and_preserves_aliases() -> None:
    payload = _v01_payload()

    item = KnowledgeItem.model_validate(payload)
    dumped = item.model_dump(mode="json")

    assert is_v01_knowledge_item_payload(payload) is True
    assert item.content_role is KnowledgeContentRole.POSITION
    assert item.provenance.boundary_review_classification == "SAFE"
    assert item.provenance.boundary_findings == [{"kind": "client_reference"}]
    assert dumped["provenance"]["kaypoh_review_classification"] == "SAFE"
    assert dumped["provenance"]["kaypoh_findings"] == [{"kind": "client_reference"}]
    assert item_from_json(json.dumps(payload)).model_dump(mode="json") == dumped


def test_sqlite_reopen_canonicalizes_v01_materialized_item_without_rewriting_event_history(tmp_path: Path) -> None:
    database = tmp_path / "solomon.sqlite3"
    store = SQLiteKnowledgeStore(database)
    payload = _v01_payload()
    with store._conn:
        store._conn.execute(
            """
            INSERT INTO knowledge_items
            (item_id, schema_version, item_json, currency_state, valid_from, valid_to, ingested_at,
             successor_id, matter_id, client_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["id"],
                payload["schema_version"],
                json.dumps(payload),
                payload["currency_state"],
                payload["valid_from"],
                None,
                payload["ingested_at"],
                None,
                None,
                None,
            ),
        )
    store.close()

    reopened = SQLiteKnowledgeStore(database)
    canonical = json.loads(reopened._conn.execute("SELECT item_json FROM knowledge_items").fetchone()["item_json"])

    assert reopened.get_item("legacy-item-1").content_role is KnowledgeContentRole.POSITION
    assert canonical["content_role"] == "position"
    assert canonical["provenance"]["boundary_review_classification"] == "SAFE"
    assert canonical["provenance"]["kaypoh_review_classification"] == "SAFE"
