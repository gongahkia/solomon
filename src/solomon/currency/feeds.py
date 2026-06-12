# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.currency.engine import register_authority_change
from solomon.currency.models import now_utc
from solomon.graph.models import ImpactResult
from solomon.graph.store import GraphStore
from solomon.store.sqlite import SQLiteKnowledgeStore


class AuthorityChange(SolomonModel):
    authority_id: str
    new_version: str
    changed_at: datetime


class AuthorityFeedMonitorState(SolomonModel):
    url: str
    etag: str | None = None
    last_modified: str | None = None
    last_checked_at: datetime | None = None


class AuthorityFeedPollResult(SolomonModel):
    url: str
    status_code: int
    changed: bool
    changes: list[AuthorityChange] = Field(default_factory=list)
    state: AuthorityFeedMonitorState


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


def poll_authority_change_feed(
    url: str,
    *,
    state: AuthorityFeedMonitorState | None = None,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> AuthorityFeedPollResult:
    headers: dict[str, str] = {"Accept": "application/json"}
    if state is not None and state.etag:
        headers["If-None-Match"] = state.etag
    if state is not None and state.last_modified:
        headers["If-Modified-Since"] = state.last_modified

    with httpx.Client(transport=transport, timeout=timeout) as client:
        response = client.get(url, headers=headers)
    if response.status_code == 304:
        next_state = AuthorityFeedMonitorState(
            url=url,
            etag=state.etag if state else None,
            last_modified=state.last_modified if state else None,
            last_checked_at=now_utc(),
        )
        return AuthorityFeedPollResult(url=url, status_code=304, changed=False, changes=[], state=next_state)

    response.raise_for_status()
    payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("changes", [])
    next_state = AuthorityFeedMonitorState(
        url=url,
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
        last_checked_at=now_utc(),
    )
    return AuthorityFeedPollResult(
        url=url,
        status_code=response.status_code,
        changed=True,
        changes=[AuthorityChange.model_validate(row) for row in rows],
        state=next_state,
    )


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
