from __future__ import annotations

from stonks_cli.chat.message_prep import sanitize_assistant_output, should_template_question


def test_should_template_question_greeting_false():
    assert should_template_question("hello") is False
    assert should_template_question("hi") is False


def test_should_template_question_keywords_true():
    assert should_template_question("analyze AAPL.US") is True
    assert should_template_question("can you backtest AAPL.US") is True


def test_should_template_question_ticker_true():
    assert should_template_question("What about AAPL.US?") is True


def test_sanitize_assistant_output_drops_slash_spam_when_not_allowed():
    raw = """hello

/sandbox/analyze AAPL.US
/sandbox/analyze AAPL.US
/sandbox
/sandbox/analyze AAPL.US
"""
    cleaned = sanitize_assistant_output(raw, allow_slash_commands=False)
    assert cleaned.strip() == "hello"


def test_sanitize_assistant_output_collapses_duplicates_when_allowed():
    raw = """/analyze AAPL.US
/analyze AAPL.US
/analyze AAPL.US
"""
    cleaned = sanitize_assistant_output(raw, allow_slash_commands=True)
    assert cleaned.strip() == "/analyze AAPL.US"
