from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplates:
    analysis_question: str


DEFAULT_TEMPLATES = PromptTemplates(
    analysis_question=(
        "User question:\n{question}\n\n"
        "How to answer (important):\n"
        "- You do NOT have access to live news, fundamentals, or company financial statements.\n"
        "- Use stonks-cli's price-based analysis/backtest capabilities instead of asking the user for financials.\n"
        "- If the question mentions a ticker, suggest the most relevant stonks-cli commands to run (e.g. 'analyze AAPL.US', 'backtest AAPL.US').\n"
        "- If you need data, ask the user to run the command and paste the report output.\n\n"
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
