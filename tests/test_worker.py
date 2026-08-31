# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from solomon.api.service import SolomonService
from solomon.api.service_models import DocumentSourceRequest
from solomon.operations.models import OperationRecord, OperationScope, OperationStatus, OperationType
from solomon.sources.models import DocumentSourceKind
from solomon.worker import run_pending_operations, sync_enabled_filesystem_sources


def test_worker_syncs_enabled_filesystem_sources_and_skips_unsupported(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "memo.txt").write_text("worker source document", encoding="utf-8")
    service.register_document_source(
        DocumentSourceRequest(name="filesystem", kind=DocumentSourceKind.FILESYSTEM, root_ref=str(source_root))
    )
    service.register_document_source(
        DocumentSourceRequest(
            name="api",
            kind=DocumentSourceKind.API,
            root_ref="https://connector.example.test/documents",
        )
    )

    batch = sync_enabled_filesystem_sources(service)

    assert batch.attempted == 1
    assert batch.succeeded == 1
    assert batch.failed == 0
    assert batch.skipped == 1


def test_worker_rejects_invalid_limit(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    with pytest.raises(ValueError, match="limit must be at least one"):
        sync_enabled_filesystem_sources(service, limit=0)


def test_worker_counts_sync_failures_and_limit_skips(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    source_root = tmp_path / "source"
    source_root.mkdir()
    service.register_document_source(
        DocumentSourceRequest(name="first", kind=DocumentSourceKind.FILESYSTEM, root_ref=str(source_root))
    )
    service.register_document_source(
        DocumentSourceRequest(name="second", kind=DocumentSourceKind.FILESYSTEM, root_ref=str(source_root))
    )

    def fail_sync(_source_id: str) -> object:
        from solomon.errors import SolomonError

        raise SolomonError("test sync failure")

    monkeypatch.setattr(service, "sync_document_source", fail_sync)

    batch = sync_enabled_filesystem_sources(service, limit=1)

    assert batch.attempted == 1
    assert batch.succeeded == 0
    assert batch.failed == 1
    assert batch.skipped == 1


def test_worker_claims_unknown_projection_once_and_retains_operator_required_record(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    operation, created = service.operation_store.create(
        OperationRecord(
            operation_type=OperationType.SUGGESTION_GENERATION,
            scope=OperationScope(matter_id="matter-a", client_id="client-a"),
            actor_id="worker-test",
            authorization_context={"service_access": "curate"},
            correlation_id="worker-test",
            idempotency_key="worker-test-operation",
        )
    )
    assert created is True

    batch = run_pending_operations(service, worker_id="worker-a")

    assert batch.attempted == 1
    assert batch.terminal == 1
    assert service.operation_store.get(operation.id).status is OperationStatus.OPERATOR_REQUIRED
