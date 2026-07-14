from __future__ import annotations

from dataclasses import dataclass

from stonks_cli.vnext.explanation_evidence import ExplanationEvidenceBundle


@dataclass(frozen=True)
class NonLLMExplanation:
    evidence: ExplanationEvidenceBundle
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, ExplanationEvidenceBundle):
            raise TypeError("non-LLM explanation requires explanation evidence")
        if not isinstance(self.text, str) or self.text != _render_explanation(self.evidence):
            raise ValueError("non-LLM explanation text is invalid")


def build_non_llm_explanation(evidence: ExplanationEvidenceBundle) -> NonLLMExplanation:
    if not isinstance(evidence, ExplanationEvidenceBundle):
        raise TypeError("non-LLM explanation requires explanation evidence")
    return NonLLMExplanation(evidence, _render_explanation(evidence))


def _render_explanation(evidence: ExplanationEvidenceBundle) -> str:
    factors = ", ".join(
        f"{component.factor_id}=raw:{component.raw_value:.6f}/normalized:{component.normalized_score:.6f}"
        for component in evidence.score_components
    )
    sources = ", ".join(
        f"{item.source_url}@{item.retrieved_at.isoformat().replace('+00:00', 'Z')}" for item in evidence.provenance
    )
    return (
        f"{evidence.rank.provider_id}:{evidence.rank.provider_asset_id} rank={evidence.rank.rank} "
        f"weighted_score={evidence.rank.weighted_score:.6f} data_confidence={evidence.data_confidence.score:.6f} "
        f"factors=[{factors}] sources=[{sources}]"
    )
