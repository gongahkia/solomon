from __future__ import annotations

from stonks_cli.chat.message_prep import (
    extract_tickers,
    is_slash_only,
    sanitize_assistant_output,
    status_for_slash_command,
    should_template_question,
    suggest_cli_commands,
)


def test_should_template_question_greeting_false():
    assert should_template_question("hello") is False
    assert should_template_question("hi") is False


def test_should_template_question_keywords_true():
    assert should_template_question("analyze AAPL.US") is True
    assert should_template_question("can you backtest AAPL.US") is True


def test_should_template_question_ticker_true():
    assert should_template_question("What about AAPL.US?") is True


def test_should_template_question_followup_with_prior_report_true():
    assert should_template_question("what are your thoughts on the above", has_prior_report=True) is True
    assert should_template_question("what are your thoughts on the above", has_prior_report=False) is False


def test_sanitize_assistant_output_drops_slash_spam_when_not_allowed():
    raw = """hello

/sandbox/analyze AAPL.US
/sandbox/analyze AAPL.US
/sandbox
/sandbox/analyze AAPL.US
"""
    cleaned = sanitize_assistant_output(raw, allow_slash_commands=False)
    assert cleaned.strip() == "hello"


def test_sanitize_assistant_output_slash_only_becomes_empty_when_not_allowed():
    raw = "/sandbox/analyze AAPL.US\n/sandbox/analyze AAPL.US\n"
    cleaned = sanitize_assistant_output(raw, allow_slash_commands=False)
    assert cleaned == ""


def test_sanitize_assistant_output_collapses_duplicates_when_allowed():
    raw = """/analyze AAPL.US
/analyze AAPL.US
/analyze AAPL.US
"""
    cleaned = sanitize_assistant_output(raw, allow_slash_commands=True)
    assert cleaned.strip() == "/analyze AAPL.US"


def test_sanitize_assistant_output_dedupes_repeated_code_blocks():
    raw = """Here you go:

```
stonks-cli analyze AAPL.US
```

```
stonks-cli analyze AAPL.US
```
"""
    cleaned = sanitize_assistant_output(raw, allow_slash_commands=True)
    assert cleaned.count("stonks-cli analyze AAPL.US") == 1


def test_sanitize_assistant_output_drops_repeated_boilerplate_lines():
    raw = """This command will analyze the stock's financial data.
This command will analyze the stock's financial data.
This command will analyze the stock's financial data.
"""
    cleaned = sanitize_assistant_output(raw, allow_slash_commands=True)
    assert cleaned.count("This command will analyze") == 1


def test_sanitize_assistant_output_removes_trailing_incomplete_fence():
    raw = """Here:

```
stonks-cli analyze AAPL.US
```
```"""
    cleaned = sanitize_assistant_output(raw, allow_slash_commands=True)
    assert not cleaned.strip().endswith("```")


def test_is_slash_only():
    assert is_slash_only("/a\n/b\n") is True
    assert is_slash_only("hello\n/a\n") is False


def test_extract_tickers_dedupes_and_preserves_order():
    assert extract_tickers("aapl.us AAPL.US msft.us") == ["AAPL.US", "MSFT.US"]


def test_suggest_cli_commands_for_ticker_message():
    cmds = suggest_cli_commands("give outlook for AAPL.US")
    assert any(c.startswith("analyze ") for c in cmds)
    assert any(c.startswith("backtest ") for c in cmds)
    assert "report" in cmds


def test_suggest_cli_commands_skips_slash_commands():
    assert suggest_cli_commands("/analyze AAPL.US") == []


def test_status_for_slash_command():
    assert status_for_slash_command("/analyze AAPL.US") == "analyzing..."
    assert status_for_slash_command("/backtest AAPL.US") == "backtesting..."
    assert status_for_slash_command("/data fetch AAPL.US") == "fetching data..."
    assert status_for_slash_command("/llm check") == "checking llm..."
    assert status_for_slash_command("/help") is None
