# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast

from solomon.currency.models import now_utc
from solomon.operations.models import OperationRecord


class OperationRequiresIntervention(RuntimeError):
    """A safe worker must stop because it cannot prove a projection remains valid."""


class OperationRunner:
    """Bounded database-claimed operation runner, intentionally limited to Solomon's current projections."""

    def __init__(
        self,
        *,
        store: Any,
        dispatch: Callable[[OperationRecord, str], OperationRecord],
        maximum_attempts: int = 3,
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum attempts must be positive")
        self._store = store
        self._dispatch = dispatch
        self._maximum_attempts = maximum_attempts

    def run_once(self, *, worker_id: str, now: datetime | None = None) -> OperationRecord | None:
        timestamp = now or now_utc()
        operation = self._store.claim_next(worker_id=worker_id, now=timestamp)
        if operation is None:
            return None
        try:
            return self._dispatch(operation, worker_id)
        except OperationRequiresIntervention as exc:
            return cast(
                OperationRecord,
                self._store.require_operator(
                    operation.id,
                    worker_id=worker_id,
                    failure_category="operator_required",
                    diagnostic=str(exc),
                ),
            )
        except Exception as exc:
            retry_delay = min(2 ** max(operation.attempt_count - 1, 0), 60)
            return cast(
                OperationRecord,
                self._store.retry(
                    operation.id,
                    worker_id=worker_id,
                    retry_at=timestamp + timedelta(seconds=retry_delay),
                    failure_category=exc.__class__.__name__.lower(),
                    diagnostic=exc.__class__.__name__,
                    maximum_attempts=self._maximum_attempts,
                ),
            )


__all__ = ["OperationRequiresIntervention", "OperationRunner"]
