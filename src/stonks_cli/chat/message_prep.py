from __future__ import annotations

import re

_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\.[A-Z]{1,5}\b")


def extract_tickers(text: str) -> list[str]:
    t = (text or "").upper()
    found = _TICKER_RE.findall(t)
    # Preserve order but de-dupe.
    out: list[str] = []
    seen: set[str] = set()
    for x in found:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def suggest_cli_commands(user_text: str) -> list[str]:
    """Return a small list of actionable stonks-cli commands for the given message."""

    t = (user_text or "").strip()
    if not t or t.lstrip().startswith("/"):
        return []

    tickers = extract_tickers(t)
    if not tickers:
        return []

    joined = " ".join(tickers)
    return [
        f"analyze {joined}",
        f"backtest {joined}",
        "report",
        "history 20",
        "help",
    ]


def should_template_question(user_text: str, *, has_prior_report: bool = False) -> bool:
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

    # Follow-up questions that reference prior output.
    if has_prior_report:
        followups = {
            "above",
            "the above",
            "that",
            "that report",
            "this report",
            "results",
            "the results",
            "summary",
            "summarize",
            "thoughts",
            "interpret",
            "interpretation",
            "explain",
        }
        if any(f in lower for f in followups):
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

    # De-duplicate repeated fenced code blocks (```...```) which some local models
    # tend to repeat many times.
    deduped: list[str] = []
    seen_blocks: set[str] = set()
    in_block = False
    block: list[str] = []
    for ln in lines:
        if ln.strip().startswith("```"):
            if not in_block:
                in_block = True
                block = [ln]
                continue
            # Closing fence
            block.append(ln)
            btxt = "\n".join(block).strip()
            if btxt and btxt not in seen_blocks:
                seen_blocks.add(btxt)
                deduped.extend(block)
            in_block = False
            block = []
            continue

        if in_block:
            block.append(ln)
        else:
            deduped.append(ln)

    # If an unterminated code block exists, include it once.
    if in_block and block:
        btxt = "\n".join(block).strip()
        if btxt and btxt not in seen_blocks:
            seen_blocks.add(btxt)
            deduped.extend(block)

    lines = deduped

    out: list[str] = []
    prev: str | None = None
    seen_counts: dict[str, int] = {}
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

        # Drop consecutive duplicates.
        if prev is not None and ln == prev:
            continue

        # Drop repeated boilerplate (even if not consecutive).
        key = s
        seen_counts[key] = seen_counts.get(key, 0) + 1
        if seen_counts[key] > 1:
            lower = key.lower()
            if lower.startswith("this command will"):
                continue
            if lower.startswith("stonks-cli "):
                continue
            if len(key) > 40:
                continue

        out.append(ln)
        prev = ln

    cleaned = "\n".join(out).strip()
    if cleaned:
        # Drop trailing incomplete backtick fences like "``" which some models emit.
        cleaned_lines = cleaned.splitlines()
        while cleaned_lines and cleaned_lines[-1].strip() in {"``", "```"}:
            cleaned_lines.pop()
        return "\n".join(cleaned_lines).strip()

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


def status_for_slash_command(cmdline: str) -> str | None:
    """Return a short status message for slow-ish /commands.

    Used to show a spinner like "analyzing..." while the command runs.
    """

    parts = (cmdline or "").strip().split()
    if not parts:
        return None
    cmd = parts[0].lower()
    args = [a.lower() for a in parts[1:]]

    if cmd == "/analyze" or cmd.startswith("/sandbox"):
        # /sandbox analyze ... will get normalized inside dispatch, but we can still
        # show a helpful status here.
        if len(args) >= 1 and args[0] in {"analyze", "/analyze"}:
            return "analyzing..."
        if cmd == "/analyze":
            return "analyzing..."

    if cmd == "/backtest":
        return "backtesting..."
    if cmd == "/report":
        return "loading report..."
    if cmd == "/doctor":
        return "checking..."
    if cmd == "/llm" and args[:1] == ["check"]:
        return "checking llm..."
    if cmd == "/data" and args[:1] == ["fetch"]:
        return "fetching data..."
    if cmd == "/data" and args[:1] == ["verify"]:
        return "verifying data..."
    if cmd == "/schedule" and args[:1] == ["status"]:
        return "checking schedule..."
    if cmd == "/schedule" and args[:1] == ["once"]:
        return "running schedule..."
    if cmd == "/schedule" and args[:1] == ["run"]:
        return "starting scheduler..."

    return None
