from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from stonks_cli.vnext.custody_readiness import CustodyReadinessEvidence, CustodyReadinessOutcome
from stonks_cli.vnext.foundation import SecretReference
from stonks_cli.vnext.live_configuration import DeferredLiveConfiguration
from stonks_cli.vnext.paper_gate import PaperGateEvidence, PaperGateOutcome
from stonks_cli.vnext.pre_execution_risk import (
    DefaultPreExecutionRiskEvaluator,
    PreExecutionRiskAssessment,
    PreExecutionRiskEvidence,
)
from stonks_cli.vnext.venue_due_diligence import VenueDueDiligenceEvidence, VenueDueDiligenceOutcome

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_pre_execution_risk_interface_can_clear_manual_review_without_authorizing_execution(tmp_path):
    assessment = DefaultPreExecutionRiskEvaluator().assess(_evidence(tmp_path))

    assert assessment == PreExecutionRiskAssessment(True, ())


def test_pre_execution_risk_interface_blocks_stale_or_failed_evidence(tmp_path):
    evidence = _evidence(tmp_path)
    failed_paper_gate = PaperGateEvidence(
        evidence.paper_gate.evidence_id,
        evidence.paper_gate.account_id,
        PaperGateOutcome.BLOCKED,
        evidence.paper_gate.started_at,
        evidence.paper_gate.completed_at,
        evidence.paper_gate.minimum_days,
        evidence.paper_gate.observed_days,
        evidence.paper_gate.decision_count,
        evidence.paper_gate.journal_sha256,
        evidence.paper_gate.tearsheet_sha256,
        evidence.paper_gate.reviewer_id,
        evidence.paper_gate.reviewed_at,
    )

    assessment = DefaultPreExecutionRiskEvaluator().assess(
        PreExecutionRiskEvidence(
            failed_paper_gate,
            evidence.venue_due_diligence,
            evidence.custody_readiness,
            evidence.live_configuration,
            NOW + timedelta(days=31),
        )
    )

    assert assessment.manual_review_ready is False
    assert assessment.blockers == (
        "custody_readiness_not_current",
        "paper_gate_not_passed",
        "venue_due_diligence_not_current",
    )


@pytest.mark.parametrize("evidence", [None, "evidence", {}])
def test_pre_execution_risk_interface_fails_closed_for_malformed_evidence(evidence):
    with pytest.raises(TypeError, match="pre-execution risk evidence is required"):
        DefaultPreExecutionRiskEvaluator().assess(evidence)  # type: ignore[arg-type]


@pytest.mark.parametrize("ready,blockers", [(True, ("paper_gate_not_passed",)), (False, ()), (False, ("b", "a"))])
def test_pre_execution_risk_assessment_rejects_inconsistent_or_noncanonical_results(ready, blockers):
    with pytest.raises(ValueError):
        PreExecutionRiskAssessment(ready, blockers)


def _evidence(tmp_path: Path) -> PreExecutionRiskEvidence:
    venue = VenueDueDiligenceEvidence(
        UUID("00000000-0000-4000-8000-000000000001"),
        "hyperliquid",
        "SG",
        VenueDueDiligenceOutcome.ALLOWED,
        "operator@example.test",
        NOW - timedelta(days=1),
        NOW + timedelta(days=30),
        ("https://www.example.test/venue-review",),
    )
    custody = CustodyReadinessEvidence(
        UUID("00000000-0000-4000-8000-000000000002"),
        "hyperliquid",
        CustodyReadinessOutcome.READY,
        SecretReference.parse("env:STONKS_CLI_VENUE_KEY"),
        "operator@example.test",
        NOW - timedelta(days=2),
        NOW - timedelta(days=1),
        NOW,
        NOW + timedelta(days=30),
        "https://www.example.test/custody-review",
    )
    paper_gate = PaperGateEvidence(
        UUID("00000000-0000-4000-8000-000000000003"),
        "paper-account",
        PaperGateOutcome.PASSED,
        NOW - timedelta(days=30),
        NOW - timedelta(minutes=1),
        30,
        30,
        3,
        "a" * 64,
        "b" * 64,
        "operator@example.test",
        NOW,
    )
    return PreExecutionRiskEvidence(
        paper_gate,
        venue,
        custody,
        DeferredLiveConfiguration(tmp_path / "live.json", "disabled"),
        NOW,
    )
