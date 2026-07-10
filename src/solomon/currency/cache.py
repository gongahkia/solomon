# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from solomon.currency.engine import CurrencyEvaluation, VerificationPolicy, evaluate_currency
from solomon.currency.models import KnowledgeItem, now_utc


class CurrencyEvaluationCache:
    """Small in-process cache keyed by item state and evaluation time bucket."""

    def __init__(self, *, policy: VerificationPolicy | None = None) -> None:
        self.policy = policy or VerificationPolicy()
        self._entries: dict[str, tuple[str, CurrencyEvaluation]] = {}

    def get_or_evaluate(self, item: KnowledgeItem, *, as_of: datetime | None = None) -> CurrencyEvaluation:
        fingerprint = _fingerprint(item, as_of=as_of, policy=self.policy)
        cached = self._entries.get(item.id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        evaluation = evaluate_currency(item, as_of=as_of, policy=self.policy)
        self._entries[item.id] = (fingerprint, evaluation)
        return evaluation

    def invalidate(self, item_ids: list[str] | set[str]) -> None:
        for item_id in item_ids:
            self._entries.pop(item_id, None)

    def contains(self, item_id: str) -> bool:
        return item_id in self._entries

    def clear(self) -> None:
        self._entries.clear()


def _fingerprint(item: KnowledgeItem, *, as_of: datetime | None, policy: VerificationPolicy) -> str:
    timestamp = as_of or now_utc()
    payload = {
        "item_id": item.id,
        "currency_state": item.currency_state.value,
        "valid_to": item.valid_to.isoformat() if item.valid_to else None,
        "successor_id": item.successor_id,
        "verified_state": item.verified_state.value,
        "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
        "metadata": item.metadata,
        "policy": policy.model_dump(mode="json"),
        "as_of_day": timestamp.date().isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
