# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from solomon.api.service import IngestRequest, SolomonService
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.deployment import (
    CheckStatus,
    DeploymentError,
    MaintenanceGate,
    compatibility_report,
    deployment_preflight,
    initialize_deployment,
    read_metadata,
)
from solomon.errors import PolicyRefusalError
from solomon.worker import run_pending_operations


def _service(tmp_path: Path) -> SolomonService:
    return SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")


def test_initialize_is_idempotent_and_preflight_reports_complete_sqlite_layout(tmp_path: Path) -> None:
    service = _service(tmp_path)
    metadata, created = initialize_deployment(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=str(tmp_path / "data" / "solomon.sqlite3"),
        owner="test-operator",
    )
    repeated, created_again = initialize_deployment(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=str(tmp_path / "data" / "solomon.sqlite3"),
        owner="test-operator",
    )
    report = deployment_preflight(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=str(tmp_path / "data" / "solomon.sqlite3"),
        require_initialized=True,
    )

    assert service.audit.verify().ok
    assert created is True
    assert created_again is False
    assert repeated == metadata == read_metadata(tmp_path / "data")
    assert report.ready is True
    assert {check.status for check in report.checks} == {CheckStatus.READY}


def test_maintenance_gate_fails_closed_for_writes_and_stops_worker_claims(tmp_path: Path) -> None:
    service = _service(tmp_path)
    gate = MaintenanceGate(tmp_path / "data")
    record = gate.acquire(reason="backup", owner="test-operator")

    with pytest.raises(PolicyRefusalError, match="maintenance"):
        service.ingest(
            IngestRequest(
                kind=KnowledgeKind.POSITION,
                content="must not persist while backup gate is active",
                source_kind=SourceKind.PARTNER,
                source_ref="maintenance-test",
            )
        )
    assert run_pending_operations(service, worker_id="worker", limit=1).model_dump() == {
        "attempted": 0,
        "completed": 0,
        "retrying": 0,
        "terminal": 0,
        "failed": 0,
    }

    gate.release(record.operation_id)
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="persists after backup gate is released",
            source_kind=SourceKind.PARTNER,
            source_ref="maintenance-test",
        )
    )
    assert item.id


def test_maintenance_gate_refuses_conflicting_or_malformed_state(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    gate = MaintenanceGate(data)
    record = gate.acquire(reason="upgrade", owner="operator-a")
    with pytest.raises(DeploymentError, match="already in maintenance"):
        gate.acquire(reason="backup", owner="operator-b")
    with pytest.raises(DeploymentError, match="different operation"):
        gate.release("wrong-operation")
    gate.release(record.operation_id)

    (data / ".solomon-maintenance.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(DeploymentError, match="operator intervention"):
        gate.active()


def test_preflight_redacts_postgres_credentials_and_profile_mismatch_is_blocked(tmp_path: Path) -> None:
    data = tmp_path / "data"
    journal = tmp_path / "journal"
    data.mkdir()
    journal.mkdir()
    initialize_deployment(
        data_dir=data,
        journal_dir=journal,
        database_url=str(data / "solomon.sqlite3"),
    )
    report = deployment_preflight(
        data_dir=data,
        journal_dir=journal,
        database_url="postgresql://alice:do-not-leak@127.0.0.1:1/solomon",
    )
    compatibility = compatibility_report(
        data_dir=data,
        database_url="postgresql://alice:do-not-leak@127.0.0.1:1/solomon",
    )

    assert "do-not-leak" not in report.model_dump_json()
    assert report.database_url == "postgresql://alice@127.0.0.1:1/solomon"
    assert report.ready is False
    assert compatibility.compatible_for_startup is False
    assert compatibility.writable is False


def test_invalid_metadata_fails_closed(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "deployment.json").write_text(json.dumps({"schema_id": "unknown"}), encoding="utf-8")

    with pytest.raises(DeploymentError, match="metadata is invalid"):
        read_metadata(data)
