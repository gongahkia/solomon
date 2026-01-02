from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplates:
    analysis_question: str


DEFAULT_TEMPLATES = PromptTemplates(
    analysis_question=(
        "Question:\n{question}\n\n"
        "Context (optional: last report snippet, may be truncated):\n{report}\n"
    )
)


def format_analysis_question(question: str, *, prior_report: str | None = None) -> str:
    q = (question or "").strip()
    r = (prior_report or "").strip()
    if not q:
        q = "(empty)"
    if not r:
        r = "(none)"
    return DEFAULT_TEMPLATES.analysis_question.format(question=q, report=r)
