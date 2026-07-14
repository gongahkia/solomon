from __future__ import annotations

from dataclasses import dataclass

from stonks_cli.vnext.explanation_evidence import ExplanationEvidenceBundle
from stonks_cli.vnext.source_citations import SourceCitation

LLM_SUMMARY_OPERATION = "summarize_evidence"


@dataclass(frozen=True)
class LLMSummaryBoundary:
    evidence: ExplanationEvidenceBundle
    citations: tuple[SourceCitation, ...]
    operation: str = LLM_SUMMARY_OPERATION

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, ExplanationEvidenceBundle):
            raise TypeError("LLM summary boundary requires explanation evidence")
        if self.operation != LLM_SUMMARY_OPERATION:
            raise ValueError("LLM summary boundary only permits evidence summaries")
        expected_citations = tuple(SourceCitation.from_provenance(item) for item in self.evidence.provenance)
        if not isinstance(self.citations, tuple) or self.citations != expected_citations:
            raise ValueError("LLM summary boundary citations do not match evidence")


def create_llm_summary_boundary(evidence: ExplanationEvidenceBundle) -> LLMSummaryBoundary:
    if not isinstance(evidence, ExplanationEvidenceBundle):
        raise TypeError("LLM summary boundary requires explanation evidence")
    return LLMSummaryBoundary(evidence, tuple(SourceCitation.from_provenance(item) for item in evidence.provenance))
