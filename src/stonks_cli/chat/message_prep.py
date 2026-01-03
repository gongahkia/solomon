from __future__ import annotations

import re

_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\.[A-Z]{1,5}\b")


def should_template_question(user_text: str) -> bool:
    """Return True if we should wrap the user question with analysis context.

    We only do this for analysis-ish queries; templating everything (e.g. greetings)
    biases local models into emitting CLI-like commands.
    """

    t = (user_text or "").strip()
    if not t:
        return False

    lower = t.lower()
    if lower.startswith("/"):
        return False

    # Short greetings / pleasantries.
    if lower in {"hi", "hello", "hey", "yo", "sup", "morning", "good morning", "good afternoon", "good evening"}:
        return False

    # Heuristic: if it mentions tickers or analysis/backtest keywords, add context.
    if _TICKER_RE.search(t):
        return True

    keywords = {
        "analyze",
        "analysis",
        "backtest",
        "strategy",
        "signals",
        "indicator",
        "rsi",
        "macd",
        "sma",
        "ema",
        "atr",
        "volatility",
        "drawdown",
        "risk",
        "stop loss",
        "take profit",
    }
    return any(k in lower for k in keywords)


def sanitize_assistant_output(text: str, *, allow_slash_commands: bool) -> str:
    """Best-effort cleanup for pathological local-model outputs.

    - Drops slash-command spam unless explicitly allowed by the user's intent.
    - Collapses consecutive duplicate lines.

    This is intentionally conservative: it should never add new content, only remove.
    """

    raw = (text or "").strip("\n")
    if not raw:
        return ""

    lines = [ln.rstrip() for ln in raw.splitlines()]

    out: list[str] = []
    prev: str | None = None
    for ln in lines:
        s = ln.strip()
        if not s:
            # Keep at most one blank line in a row.
            if out and out[-1] == "":
                continue
            out.append("")
            prev = ln
            continue

        if not allow_slash_commands and s.startswith("/"):
            continue

        if prev is not None and ln == prev:
            continue

        out.append(ln)
        prev = ln

    cleaned = "\n".join(out).strip()
    if cleaned:
        return cleaned

    # If we dropped everything (e.g. slash-command-only spam), return empty.
    return ""


def is_slash_only(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if not lines:
        return False
    return all(ln.startswith("/") for ln in lines)
