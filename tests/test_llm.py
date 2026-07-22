from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from conftest import encrypted_ledger

from stonks_cli.config import LLMSettings
from stonks_cli.errors import LLMError, ProfileError
from stonks_cli.llm import (
    LLMUsage,
    budget_status,
    coding_agent_wrapper,
    complete,
    news_prompt,
    validate_public_question,
)


def test_cloud_provider_requires_explicit_privacy_acknowledgement() -> None:
    with pytest.raises(ProfileError, match="explicit privacy"):
        LLMSettings(provider="openai", model="model")
    with pytest.raises(ProfileError, match="local-only"):
        LLMSettings(provider="ollama", model="model")


def test_ollama_uses_loopback_chat_api_and_records_encrypted_usage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    requests: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def transport(url, headers, payload, timeout):
        assert timeout == 90
        requests.append((url, dict(headers), payload))
        return {
            "model": "tiny",
            "message": {"role": "assistant", "content": "summary"},
            "prompt_eval_count": 4,
            "eval_count": 3,
        }

    settings = LLMSettings(provider="ollama", model="tiny", ollama_local_only=True)
    result = complete(ledger, settings, system="facts only", prompt="public article", transport=transport)

    assert result.text == "summary"
    assert result.usage == LLMUsage(4, 3)
    assert requests == [
        (
            "http://127.0.0.1:11434/api/chat",
            {"Content-Type": "application/json"},
            {
                "model": "tiny",
                "messages": [
                    {"role": "system", "content": "facts only"},
                    {"role": "user", "content": "public article"},
                ],
                "stream": False,
                "options": {"num_predict": 600},
            },
        )
    ]
    assert ledger.path.read_bytes().startswith(b"STONKS")


@pytest.mark.parametrize(
    ("provider", "environment", "response", "expected_url", "expected_header"),
    (
        (
            "openai",
            "OPENAI_API_KEY",
            {
                "model": "cloud-model",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "openai text"}],
                    }
                ],
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
            "https://api.openai.com/v1/responses",
            ("Authorization", "Bearer key"),
        ),
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            {
                "model": "cloud-model",
                "content": [{"type": "text", "text": "anthropic text"}],
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
            "https://api.anthropic.com/v1/messages",
            ("x-api-key", "key"),
        ),
        (
            "gemini",
            "GEMINI_API_KEY",
            {
                "candidates": [{"content": {"parts": [{"text": "gemini text"}]}}],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3},
            },
            "https://generativelanguage.googleapis.com/v1beta/models/cloud-model:generateContent",
            ("x-goog-api-key", "key"),
        ),
    ),
)
def test_cloud_adapters_send_one_text_request_without_tools(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    environment: str,
    response: dict[str, object],
    expected_url: str,
    expected_header: tuple[str, str],
) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    seen: dict[str, object] = {}
    monkeypatch.setenv(environment, "key")

    def transport(url, headers, payload, timeout):
        seen["url"] = url
        seen["headers"] = dict(headers)
        seen["payload"] = payload
        return response

    result = complete(
        ledger,
        LLMSettings(provider=provider, model="cloud-model", allow_cloud=True),
        system="system",
        prompt="public question",
        transport=transport,
    )

    assert result.usage == LLMUsage(2, 3)
    assert seen["url"] == expected_url
    assert seen["headers"][expected_header[0]] == expected_header[1]
    assert "tools" not in seen["payload"]
    if provider in {"openai", "gemini"}:
        assert seen["payload"]["store"] is False


def test_daily_budget_prevents_another_request_after_recorded_usage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    settings = LLMSettings(
        provider="ollama",
        model="tiny",
        ollama_local_only=True,
        budget_period="daily",
        budget_limit_sgd="1",
        output_cost_per_million_sgd="1000000",
        max_output_tokens=1,
    )

    def transport(url, headers, payload, timeout):
        return {
            "model": "tiny",
            "message": {"role": "assistant", "content": "one"},
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    moment = datetime(2026, 7, 22, tzinfo=UTC)
    assert complete(
        ledger, settings, system="a", prompt="b", transport=transport, now=moment
    ).estimated_cost_sgd == Decimal("1")
    assert budget_status(ledger, settings, moment).remaining_sgd == Decimal("0")
    with pytest.raises(LLMError, match="budget"):
        complete(ledger, settings, system="a", prompt="b", transport=transport, now=moment)


def test_public_prompts_and_agent_wrappers_block_obvious_private_data() -> None:
    assert validate_public_question("What is an ETF?") == "What is an ETF?"
    with pytest.raises(LLMError, match="private-data"):
        validate_public_question("Summarize my account 12345678")
    assert coding_agent_wrapper("pi", "What is inflation?")[:2] == ("pi", "-p")
    with pytest.raises(LLMError, match="private-data"):
        coding_agent_wrapper("codex", "Review my portfolio")


def test_news_prompt_requires_public_https_provenance() -> None:
    system, prompt = news_prompt("https://example.com/news", "public article text")
    assert "personalized financial advice" in system
    assert "https://example.com/news" in prompt
    with pytest.raises(LLMError, match="HTTPS"):
        news_prompt("http://example.com/news", "public article text")
