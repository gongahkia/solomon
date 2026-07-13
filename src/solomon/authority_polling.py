# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.authority_sources import AuthorityPollDeadLetter, SQLiteAuthoritySourceRegistry
from solomon.contracts import AuthoritySourceAdapter, AuthoritySourceKind
from solomon.currency.models import now_utc
from solomon.workflow.models import AuthorityChangeEvent


class AuthorityPollResult(SolomonModel):
    event_id: str
    source_id: str
    state: Literal["succeeded", "retrying", "dead_lettered"]
    events_received: int = Field(default=0, ge=0)
    review_obligations_created: int = Field(default=0, ge=0)
    error: str | None = None
    retry_at: datetime | None = None


class AuthorityPollBatch(SolomonModel):
    scheduled: int = Field(default=0, ge=0)
    results: list[AuthorityPollResult] = Field(default_factory=list)


class AuthorityPollRetryPolicy(SolomonModel):
    max_attempts: int = Field(default=3, ge=1)
    initial_delay_seconds: int = Field(default=30, ge=1)

    def retry_at(self, *, failed_at: datetime, attempt: int) -> datetime:
        return failed_at + timedelta(seconds=self.initial_delay_seconds * (2 ** (attempt - 1)))

    @staticmethod
    def is_transient(error: Exception) -> bool:
        return isinstance(error, (ConnectionError, OSError, TimeoutError))


class AuthorityPollOutbox:
    def __init__(
        self,
        *,
        registry: SQLiteAuthoritySourceRegistry,
        adapters: Mapping[AuthoritySourceKind, AuthoritySourceAdapter],
        consume_event: Callable[[AuthorityChangeEvent], dict[str, Any]],
        retry_policy: AuthorityPollRetryPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.adapters = adapters
        self.consume_event = consume_event
        self.retry_policy = retry_policy or AuthorityPollRetryPolicy()

    def schedule_due(self, *, as_of: datetime | None = None) -> list[str]:
        return [record.event.event_id for record in self.registry.schedule_due_polls(as_of=as_of)]

    def run_due(self, *, as_of: datetime | None = None, limit: int = 100) -> AuthorityPollBatch:
        now = as_of or now_utc()
        results: list[AuthorityPollResult] = []
        for record in self.registry.pending_poll_events(limit=limit, available_before=now):
            source_id = record.event.aggregate_id
            try:
                source = self.registry.get(source_id)
                adapter = self.adapters.get(source.kind)
                if adapter is None:
                    raise ValueError(f"no authority poll adapter configured for {source.kind.value}")
                events, checkpoint = adapter.poll(source, self.registry.get_poll_checkpoint(source_id))
                if any(event.source_id != source_id for event in events):
                    raise ValueError("authority poll adapter returned an event for another source")
                obligation_count = 0
                for event in events:
                    outcome = self.consume_event(event)
                    review_tasks = outcome.get("review_tasks")
                    if not bool(outcome.get("duplicate")) and isinstance(review_tasks, list):
                        obligation_count += len(review_tasks)
                self.registry.complete_poll(record.event.event_id, checkpoint=checkpoint, completed_at=now)
                results.append(
                    AuthorityPollResult(
                        event_id=record.event.event_id,
                        source_id=source_id,
                        state="succeeded",
                        events_received=len(events),
                        review_obligations_created=obligation_count,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                error = f"{exc.__class__.__name__}: {exc}"
                attempts = record.delivery_attempts + 1
                dead_letter = not self.retry_policy.is_transient(exc) or attempts >= self.retry_policy.max_attempts
                retry_at = None if dead_letter else self.retry_policy.retry_at(failed_at=now, attempt=attempts)
                self.registry.record_poll_failure(
                    record.event.event_id,
                    error=error,
                    retry_at=retry_at,
                    dead_letter=dead_letter,
                    failed_at=now,
                )
                results.append(
                    AuthorityPollResult(
                        event_id=record.event.event_id,
                        source_id=source_id,
                        state="dead_lettered" if dead_letter else "retrying",
                        error=error,
                        retry_at=retry_at,
                    )
                )
        return AuthorityPollBatch(results=results)

    def dead_letters(self, *, limit: int = 100) -> list[AuthorityPollDeadLetter]:
        return self.registry.dead_letter_poll_events(limit=limit)

    def retry_dead_letter(self, event_id: str, *, as_of: datetime | None = None) -> None:
        self.registry.requeue_dead_letter(event_id, available_at=as_of)


__all__ = [
    "AuthorityPollBatch",
    "AuthorityPollOutbox",
    "AuthorityPollResult",
    "AuthorityPollRetryPolicy",
]
