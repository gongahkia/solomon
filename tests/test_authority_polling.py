# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from solomon.api.service import DependencyRequest, IngestRequest, SolomonService
from solomon.contracts import AdapterHealth, AuthorityPollSchedule, AuthoritySource, AuthoritySourceKind, SyncCheckpoint
from solomon.currency.models import CurrencyState, KnowledgeKind, SourceKind, VerifiedState
from solomon.graph.models import EdgeType
from solomon.workflow.models import AuthorityChangeEvent

POLL_AT = datetime(2026, 7, 13, 8, 30, tzinfo=timezone.utc)


class FixtureAuthorityAdapter:
    kind = AuthoritySourceKind.API

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.checkpoints: list[SyncCheckpoint | None] = []

    def health(self, _source: AuthoritySource) -> AdapterHealth:
        return AdapterHealth(healthy=not self.fail)

    def poll(
        self,
        source: AuthoritySource,
        checkpoint: SyncCheckpoint | None,
    ) -> tuple[list[AuthorityChangeEvent], SyncCheckpoint | None]:
        self.checkpoints.append(checkpoint)
        if self.fail:
            raise RuntimeError("connector unavailable")
        return (
            [
                AuthorityChangeEvent(
                    source_id=source.id,
                    idempotency_key="regulation-r-12:v2",
                    authority_id="regulation-r-12",
                    previous_version="v1",
                    new_version="v2",
                    changed_at=POLL_AT,
                    evidence_url="https://gazette.test/regulation-r-12/v2",
                    diff={"sections_changed": ["12"]},
                )
            ],
            SyncCheckpoint(source_id=source.id, cursor="cursor-v2", observed_at=POLL_AT),
        )

    def checkpoint(self, source: AuthoritySource) -> SyncCheckpoint | None:
        return SyncCheckpoint(source_id=source.id, cursor="cursor-v2", observed_at=POLL_AT)

    def replay(self, _source: AuthoritySource, _checkpoint: SyncCheckpoint) -> list[AuthorityChangeEvent]:
        return []


def _source() -> AuthoritySource:
    return AuthoritySource(
        id="official-gazette",
        name="official gazette",
        kind=AuthoritySourceKind.API,
        root_ref="https://gazette.test/api",
        poll_schedule=AuthorityPollSchedule(interval_seconds=60),
    )


def _service_with_dependent_position(tmp_path: Path) -> tuple[SolomonService, str]:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Structure X relies on Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="regulation-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    service.register_authority_source(_source())
    return service, item.id


def test_durable_authority_polling_persists_checkpoint_and_creates_review_obligation(tmp_path: Path) -> None:
    service, item_id = _service_with_dependent_position(tmp_path)
    adapter = FixtureAuthorityAdapter()

    scheduled = service.schedule_authority_polls(as_of=POLL_AT)
    duplicate_pending_schedule = service.schedule_authority_polls(as_of=POLL_AT)
    batch = service.run_authority_polls({AuthoritySourceKind.API: adapter}, as_of=POLL_AT)
    next_due = POLL_AT + timedelta(seconds=60)
    duplicate_scheduled = service.schedule_authority_polls(as_of=next_due)
    duplicate_batch = service.run_authority_polls({AuthoritySourceKind.API: adapter}, as_of=next_due)

    assert len(scheduled) == 1
    assert duplicate_pending_schedule == []
    assert batch.results[0].state == "succeeded"
    assert batch.results[0].events_received == 1
    assert batch.results[0].review_obligations_created == 1
    assert service.authority_sources.get_poll_checkpoint("official-gazette") == SyncCheckpoint(
        source_id="official-gazette", cursor="cursor-v2", observed_at=POLL_AT
    )
    assert len(service.review_tasks()) == 1
    polled_item = service.store.get_item(item_id)
    assert polled_item.currency_state is CurrencyState.STALE_PENDING_REVERIFICATION
    assert polled_item.verified_state is VerifiedState.VERIFIED
    assert polled_item.content == "Structure X relies on Regulation R section 12."
    assert len(duplicate_scheduled) == 1
    assert duplicate_batch.results[0].state == "succeeded"
    assert duplicate_batch.results[0].review_obligations_created == 0
    assert len(service.review_tasks()) == 1
    assert adapter.checkpoints == [
        None,
        SyncCheckpoint(source_id="official-gazette", cursor="cursor-v2", observed_at=POLL_AT),
    ]


def test_authority_polling_keeps_failed_work_pending_without_advancing_checkpoint(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    service.register_authority_source(_source())
    adapter = FixtureAuthorityAdapter(fail=True)

    service.schedule_authority_polls(as_of=POLL_AT)
    batch = service.run_authority_polls({AuthoritySourceKind.API: adapter}, as_of=POLL_AT)
    pending = service.authority_sources.pending_poll_events(available_before=POLL_AT)

    assert batch.results[0].state == "failed"
    assert "connector unavailable" in (batch.results[0].error or "")
    assert len(pending) == 1
    assert pending[0].delivery_attempts == 1
    assert service.authority_sources.get_poll_checkpoint("official-gazette") is None
