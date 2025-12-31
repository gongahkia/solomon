from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplates:
    analysis_question: str


DEFAULT_TEMPLATES = PromptTemplates(
    analysis_question=(
           "You are stonks-cli, a local CLI assistant for stock analysis.\n"
        "Important: You are not a financial advisor. Provide informational guidance only.\n\n"
        "When useful, suggest concrete CLI commands (e.g. /analyze AAPL.US).\n\n"
        "If a prior report is provided, use it as context and cite tickers/actions from it.\n\n"
        "User question:\n{question}\n\n"
        "Prior report (optional, may be truncated):\n{report}\n"
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
