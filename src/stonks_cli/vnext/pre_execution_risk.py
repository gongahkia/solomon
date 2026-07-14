from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from stonks_cli.vnext.custody_readiness import CustodyReadinessEvidence
from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.live_configuration import DeferredLiveConfiguration
from stonks_cli.vnext.paper_gate import PaperGateEvidence
from stonks_cli.vnext.venue_due_diligence import VenueDueDiligenceEvidence


@dataclass(frozen=True)
class PreExecutionRiskEvidence:
    paper_gate: PaperGateEvidence
    venue_due_diligence: VenueDueDiligenceEvidence
    custody_readiness: CustodyReadinessEvidence
    live_configuration: DeferredLiveConfiguration
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.paper_gate, PaperGateEvidence):
            raise TypeError("pre-execution risk paper-gate evidence is invalid")
        if not isinstance(self.venue_due_diligence, VenueDueDiligenceEvidence):
            raise TypeError("pre-execution risk venue evidence is invalid")
        if not isinstance(self.custody_readiness, CustodyReadinessEvidence):
            raise TypeError("pre-execution risk custody evidence is invalid")
        if not isinstance(self.live_configuration, DeferredLiveConfiguration):
            raise TypeError("pre-execution risk live configuration is invalid")
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))


@dataclass(frozen=True)
class PreExecutionRiskAssessment:
    manual_review_ready: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.manual_review_ready, bool):
            raise TypeError("pre-execution risk readiness is invalid")
        if not isinstance(self.blockers, tuple) or not all(isinstance(blocker, str) and blocker for blocker in self.blockers):
            raise ValueError("pre-execution risk blockers are invalid")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ValueError("pre-execution risk blockers are not canonical")
        if self.manual_review_ready is bool(self.blockers):
            raise ValueError("pre-execution risk readiness does not match blockers")


class PreExecutionRiskEvaluator(Protocol):
    def assess(self, evidence: PreExecutionRiskEvidence) -> PreExecutionRiskAssessment: ...


class DefaultPreExecutionRiskEvaluator:
    """Evaluates evidence for manual review only; it cannot authorize broker execution."""

    def assess(self, evidence: PreExecutionRiskEvidence) -> PreExecutionRiskAssessment:
        if not isinstance(evidence, PreExecutionRiskEvidence):
            raise TypeError("pre-execution risk evidence is required")
        blockers: list[str] = []
        if not evidence.paper_gate.passed:
            blockers.append("paper_gate_not_passed")
        if not evidence.venue_due_diligence.is_current_at(evidence.evaluated_at):
            blockers.append("venue_due_diligence_not_current")
        if not evidence.custody_readiness.is_current_at(evidence.evaluated_at):
            blockers.append("custody_readiness_not_current")
        if evidence.live_configuration.execution_mode != "disabled":
            blockers.append("live_configuration_not_disabled")
        canonical_blockers = tuple(sorted(set(blockers)))
        return PreExecutionRiskAssessment(manual_review_ready=not canonical_blockers, blockers=canonical_blockers)
