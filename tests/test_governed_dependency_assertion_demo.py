# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from solomon.api.service import SolomonService
from solomon.operations.models import OperationStatus
from solomon.worker import run_pending_operations

ROOT = Path(__file__).resolve().parents[1]


def test_governed_dependency_assertion_proof_matches_deterministic_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "governed-dependency-assertion-proof"
    subprocess.run(  # noqa: S603 - invokes the repository's fixed local scenario script.
        [
            sys.executable,
            "examples/scenarios/governed-dependency-assertion-proof/run.py",
            "--workspace",
            str(workspace),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    expected = json.loads(
        (ROOT / "tests/fixtures/governed-dependency-assertion-proof-snapshot.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads((workspace / "governed-dependency-assertion-proof-snapshot.json").read_text(encoding="utf-8"))
    result = json.loads((workspace / "governed-dependency-assertion-proof-result.json").read_text(encoding="utf-8"))

    assert snapshot == expected
    assert result["latency_ms"] <= result["latency_budget_ms"]
    assert (workspace / "audit-pack" / "manifest.json").exists()


def test_governed_proof_can_queue_and_resume_a_valid_confirmation(tmp_path: Path) -> None:
    workspace = tmp_path / "governed-dependency-assertion-recovery"
    subprocess.run(  # noqa: S603 - invokes the repository's fixed local scenario script.
        [
            sys.executable,
            "examples/scenarios/governed-dependency-assertion-proof/run.py",
            "--workspace",
            str(workspace),
            "--queue-recovery-operation",
            "--serial-confirmation",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    snapshot = json.loads((workspace / "governed-dependency-assertion-proof-snapshot.json").read_text(encoding="utf-8"))
    service = SolomonService(data_dir=workspace / "data", journal_dir=workspace / "journal")

    queued = [
        operation
        for operation in service.operation_store.list(limit=10_000)
        if operation.idempotency_key == "backup-recovery-confirmation-operation"
    ]
    batch = run_pending_operations(service, worker_id="governed-recovery-test")

    assert snapshot["operation_recovery"] == {"queued_confirmation": True}
    assert snapshot["idempotency"]["concurrent_confirmations"] == 1
    assert len(queued) == 1 and queued[0].status is OperationStatus.QUEUED
    assert batch.completed >= 1
    assert service.consistency_check(matter_id="matter-alpha", client_id="client-alpha").findings == []
