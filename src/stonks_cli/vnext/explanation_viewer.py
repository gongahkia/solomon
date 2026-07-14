from __future__ import annotations

from dataclasses import dataclass

from stonks_cli.vnext.explanation_evidence import ExplanationEvidenceBundle
from stonks_cli.vnext.score_components import ScoreComponent


@dataclass(frozen=True)
class InteractiveExplanationViewer:
    evidence: ExplanationEvidenceBundle
    selected_factor_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, ExplanationEvidenceBundle):
            raise TypeError("interactive explanation viewer requires evidence")
        if self.selected_factor_id is not None and self.selected_factor_id not in self.factor_ids:
            raise ValueError("interactive explanation viewer factor is invalid")

    @property
    def factor_ids(self) -> tuple[str, ...]:
        return tuple(component.factor_id for component in self.evidence.score_components)

    @property
    def selected_component(self) -> ScoreComponent | None:
        if self.selected_factor_id is None:
            return None
        return next(component for component in self.evidence.score_components if component.factor_id == self.selected_factor_id)

    def select_factor(self, factor_id: str) -> InteractiveExplanationViewer:
        if not isinstance(factor_id, str) or factor_id not in self.factor_ids:
            raise ValueError("interactive explanation viewer factor is invalid")
        return InteractiveExplanationViewer(self.evidence, factor_id)

    def render(self) -> str:
        lines = [
            "EXPLANATION VIEWER",
            f"asset: {self.evidence.rank.provider_id}:{self.evidence.rank.provider_asset_id}",
            f"rank: {self.evidence.rank.rank}",
            f"weighted_score: {self.evidence.rank.weighted_score:.6f}",
            f"data_confidence: {self.evidence.data_confidence.score:.6f}",
            f"available_factors: {', '.join(self.factor_ids)}",
        ]
        component = self.selected_component
        if component is not None:
            weight = dict(self.evidence.factor_weights)[component.factor_id]
            lines.extend(
                (
                    f"selected_factor: {component.factor_id}",
                    f"raw_value: {component.raw_value:.6f}",
                    f"normalized_score: {component.normalized_score:.6f}",
                    f"weight: {weight:.6f}",
                    f"contribution: {component.normalized_score * weight:.6f}",
                )
            )
        lines.append("sources:")
        lines.extend(f"- {item.source_url}@{item.retrieved_at.isoformat().replace('+00:00', 'Z')}" for item in self.evidence.provenance)
        return "\n".join(lines)
