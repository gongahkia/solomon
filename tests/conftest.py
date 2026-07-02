# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from hypothesis import HealthCheck, settings

import solomon.api.service as api_service
import solomon.audit.journal as audit_journal
import solomon.credence.policy as credence_policy
import solomon.currency.cache as currency_cache
import solomon.currency.engine as currency_engine
import solomon.currency.feeds as currency_feeds
import solomon.currency.models as currency_models
import solomon.currency.prediction as currency_prediction
import solomon.graph.models as graph_models
import solomon.graph.propagation as graph_propagation
import solomon.graph.suggestions as graph_suggestions

FROZEN_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
_REAL_RECORD_VERIFICATION = currency_engine.record_verification

settings.register_profile(
    "solomon",
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
settings.load_profile("solomon")


def _frozen_now_utc() -> datetime:
    return FROZEN_NOW


def _record_verification_with_real_timestamp(
    item: currency_models.KnowledgeItem,
    *,
    by: str,
    outcome: Any,
    recorded_at: datetime | None = None,
    successor_id: str | None = None,
) -> currency_engine.RecordedVerification:
    return _REAL_RECORD_VERIFICATION(
        item,
        by=by,
        outcome=outcome,
        recorded_at=recorded_at or datetime.now(timezone.utc),
        successor_id=successor_id,
    )


@pytest.fixture(autouse=True)
def freeze_solomon_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = [
        audit_journal,
        credence_policy,
        currency_cache,
        currency_engine,
        currency_feeds,
        currency_models,
        currency_prediction,
        graph_models,
        graph_propagation,
        graph_suggestions,
    ]
    for module in modules:
        monkeypatch.setattr(module, "now_utc", _frozen_now_utc, raising=False)
    monkeypatch.setattr(api_service, "record_verification", _record_verification_with_real_timestamp)
