from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stonks_cli.paths import default_state_dir


@dataclass(frozen=True)
class ResearchThesis:
    market_id: str
    token_id: str | None
    question: str
    provider: str
    confidence: float
    passed_checks: int
    checks: dict[str, bool]
    thesis: str
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def thesis_cache_path() -> Path:
    return default_state_dir() / "polymarket_theses.json"


def load_theses(path: Path | None = None) -> list[ResearchThesis]:
    use_path = path or thesis_cache_path()
    if not use_path.exists():
        return []
    payload = json.loads(use_path.read_text(encoding="utf-8"))
    return [ResearchThesis(**item) for item in payload]


def save_thesis(thesis: ResearchThesis, path: Path | None = None) -> None:
    use_path = path or thesis_cache_path()
    use_path.parent.mkdir(parents=True, exist_ok=True)
    theses = [item for item in load_theses(use_path) if item.market_id != thesis.market_id or item.token_id != thesis.token_id]
    theses.append(thesis)
    use_path.write_text(json.dumps([item.to_dict() for item in theses], indent=2), encoding="utf-8")


def build_research_prompt(scan: dict[str, Any], wallet_context: list[dict[str, Any]] | None = None) -> str:
    context = {
        "market": scan,
        "wallet_context": wallet_context or [],
        "required_checks": ["base_rate", "recent_news", "whale_presence", "crowd_disposition"],
        "decision_rule": "Only pass if at least 3 of 4 checks support the trade and confidence is above 0.75.",
    }
    return (
        "You are evaluating a Polymarket trade candidate outside the live execution hot path. "
        "Return compact JSON with keys: confidence, checks, thesis. "
        "checks must contain booleans for base_rate, recent_news, whale_presence, crowd_disposition.\n\n"
        f"{json.dumps(context, separators=(',', ':'))}"
    )


def generate_thesis(
    scan: dict[str, Any],
    *,
    provider: str = "claude",
    model: str | None = None,
    api_key_env: str | None = None,
    wallet_context: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> ResearchThesis:
    prompt = build_research_prompt(scan, wallet_context)
    if dry_run:
        payload = {
            "confidence": 0.0,
            "checks": {
                "base_rate": False,
                "recent_news": False,
                "whale_presence": bool(scan.get("target_wallet_count")),
                "crowd_disposition": False,
            },
            "thesis": "dry-run research prompt generated; no LLM call made",
        }
    elif provider == "claude":
        payload = _call_claude(prompt, model or "claude-3-5-sonnet-latest", api_key_env or "ANTHROPIC_API_KEY")
    elif provider in {"openai", "codex"}:
        payload = _call_openai(prompt, model or "gpt-4.1-mini", api_key_env or "OPENAI_API_KEY")
    else:
        raise ValueError(f"unsupported research provider: {provider}")

    checks = {key: bool(payload.get("checks", {}).get(key)) for key in ("base_rate", "recent_news", "whale_presence", "crowd_disposition")}
    passed_checks = sum(1 for value in checks.values() if value)
    return ResearchThesis(
        market_id=str(scan.get("market_id") or ""),
        token_id=str(scan.get("token_id")) if scan.get("token_id") is not None else None,
        question=str(scan.get("question") or ""),
        provider=provider,
        confidence=float(payload.get("confidence") or 0.0),
        passed_checks=passed_checks,
        checks=checks,
        thesis=str(payload.get("thesis") or ""),
        generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


def _call_claude(prompt: str, model: str, api_key_env: str) -> dict[str, Any]:
    key = _required_env(api_key_env)
    body = {
        "model": model,
        "max_tokens": 700,
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    response = _json_request(request)
    text = "".join(block.get("text", "") for block in response.get("content", []) if isinstance(block, dict))
    return _parse_llm_json(text)


def _call_openai(prompt: str, model: str, api_key_env: str) -> dict[str, Any]:
    key = _required_env(api_key_env)
    body = {
        "model": model,
        "input": prompt,
        "text": {"format": {"type": "json_object"}},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
        method="POST",
    )
    response = _json_request(request)
    text = response.get("output_text") or ""
    if not text:
        chunks: list[str] = []
        for item in response.get("output", []):
            for content in item.get("content", []):
                if isinstance(content, dict) and "text" in content:
                    chunks.append(str(content["text"]))
        text = "".join(chunks)
    return _parse_llm_json(text)


def _json_request(request: urllib.request.Request) -> dict[str, Any]:
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    return json.loads(cleaned)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"{name} is required for LLM research")
    return value
