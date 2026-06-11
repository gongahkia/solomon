# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from solomon.api.schemas import SolomonModel
from solomon.currency.engine import register_authority_change
from solomon.graph.models import ImpactResult
from solomon.graph.store import GraphStore
from solomon.store.sqlite import SQLiteKnowledgeStore


class AuthorityChange(SolomonModel):
    authority_id: str
    new_version: str
    changed_at: datetime


def load_authority_changes(path: Path | str) -> list[AuthorityChange]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        raw = json.loads(source.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("changes", [])
    elif source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    else:
        raise ValueError("authority feed must be .json or .csv")
    return [AuthorityChange.model_validate(row) for row in rows]


def apply_authority_changes(
    changes: list[AuthorityChange],
    *,
    graph: GraphStore,
    store: SQLiteKnowledgeStore,
) -> list[ImpactResult]:
    return [
        register_authority_change(
            authority_id=change.authority_id,
            new_version=change.new_version,
            changed_at=change.changed_at,
            graph=graph,
            store=store,
        )
        for change in changes
    ]

