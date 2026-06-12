# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import time
from enum import Enum
from http import HTTPStatus
from typing import Any, Literal, Protocol

import httpx
from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.currency.models import Matter


class EndpointKind(str, Enum):
    REMOTE_ZDR = "remote_zdr"
    LOCAL = "local"


class ModelRequest(SolomonModel):
    prompt: str
    matter_id: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.0


class ModelResponse(SolomonModel):
    text: str
    endpoint: EndpointKind
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelCallAudit(SolomonModel):
    endpoint: EndpointKind
    reason: str
    crossed_boundary: bool
    fallback_used: bool = False
    quality_caveat: str | None = None
    prompt_sha256: str
    prompt_chars: int
    latency_ms: float
    cost_usd: float | None = None


class ModelEndpoint(Protocol):
    kind: EndpointKind

    def complete(self, request: ModelRequest) -> ModelResponse: ...


class RemoteZDREndpoint:
    kind = EndpointKind.REMOTE_ZDR

    def __init__(
        self,
        *,
        url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.transport = transport

    def complete(self, request: ModelRequest) -> ModelResponse:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = _post_json_with_retries(
            self.url,
            payload=request.model_dump(mode="json"),
            headers=headers,
            timeout=self.timeout,
            retries=self.retries,
            retry_backoff_seconds=self.retry_backoff_seconds,
            transport=self.transport,
        )
        payload = response.json()
        return ModelResponse(
            text=str(payload.get("text", payload.get("response", ""))),
            endpoint=self.kind,
            metadata={k: v for k, v in payload.items() if k not in {"text", "response"}},
        )


class OpenAIResponsesEndpoint:
    kind = EndpointKind.REMOTE_ZDR

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        url: str = "https://api.openai.com/v1/responses",
        timeout: float = 30.0,
        retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.transport = transport

    def complete(self, request: ModelRequest) -> ModelResponse:
        response = _post_json_with_retries(
            self.url,
            payload={
                "model": self.model,
                "input": request.prompt,
                "max_output_tokens": request.max_tokens,
                "temperature": request.temperature,
            },
            headers={"Accept": "application/json", "Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
            retries=self.retries,
            retry_backoff_seconds=self.retry_backoff_seconds,
            transport=self.transport,
        )
        payload = response.json()
        text = _extract_openai_response_text(payload)
        return ModelResponse(
            text=text,
            endpoint=self.kind,
            metadata={
                "provider": "openai-responses",
                "model": payload.get("model", self.model),
                "response_id": payload.get("id"),
                "usage": payload.get("usage"),
            },
        )


class LocalModelEndpoint:
    kind = EndpointKind.LOCAL

    def __init__(self, *, url: str = "http://127.0.0.1:11434/api/generate", timeout: float = 60.0) -> None:
        self.url = url
        self.timeout = timeout

    def complete(self, request: ModelRequest) -> ModelResponse:
        response = httpx.post(
            self.url,
            json={
                "prompt": request.prompt,
                "stream": False,
                "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return ModelResponse(
            text=str(payload.get("response", payload.get("text", ""))),
            endpoint=self.kind,
            metadata={k: v for k, v in payload.items() if k not in {"text", "response"}},
        )


class RoutingPolicy(SolomonModel):
    remote_allowed: bool = True
    strict_local_only: bool = True
    fallback_to_local_on_remote_error: bool = True
    zero_egress_mode: bool = False


class RoutingDecision(SolomonModel):
    endpoint: EndpointKind
    reason: str
    crossed_boundary: bool


class RoutedModelResult(SolomonModel):
    response: ModelResponse
    audit: ModelCallAudit


def classify_matter_sensitivity(matter: Matter | None) -> Literal["standard", "confidential", "strict"]:
    if matter is None:
        return "standard"
    return matter.sensitivity


class ModelRouter:
    def __init__(
        self,
        *,
        remote: ModelEndpoint,
        local: ModelEndpoint,
        policy: RoutingPolicy | None = None,
    ) -> None:
        self.remote = remote
        self.local = local
        self.policy = policy or RoutingPolicy()

    def decide(self, *, matter: Matter | None) -> RoutingDecision:
        sensitivity = classify_matter_sensitivity(matter)
        if self.policy.zero_egress_mode:
            return RoutingDecision(
                endpoint=EndpointKind.LOCAL,
                reason="zero-egress mode forces local endpoint",
                crossed_boundary=False,
            )
        if sensitivity == "strict" and self.policy.strict_local_only:
            return RoutingDecision(
                endpoint=EndpointKind.LOCAL,
                reason="strict matter sensitivity forbids remote egress",
                crossed_boundary=False,
            )
        if self.policy.remote_allowed:
            return RoutingDecision(
                endpoint=EndpointKind.REMOTE_ZDR,
                reason=f"{sensitivity} matter may use remote ZDR with sanitized context",
                crossed_boundary=True,
            )
        return RoutingDecision(
            endpoint=EndpointKind.LOCAL,
            reason="remote endpoint disabled by policy",
            crossed_boundary=False,
        )

    def complete(self, request: ModelRequest, *, matter: Matter | None = None) -> RoutedModelResult:
        decision = self.decide(matter=matter)
        start = time.perf_counter()
        fallback_used = False
        quality_caveat: str | None = None
        endpoint = self.remote if decision.endpoint is EndpointKind.REMOTE_ZDR else self.local
        try:
            response = endpoint.complete(request)
        except Exception:
            if decision.endpoint is not EndpointKind.REMOTE_ZDR or not self.policy.fallback_to_local_on_remote_error:
                raise
            fallback_used = True
            quality_caveat = "remote endpoint unavailable; local model fallback used"
            decision = RoutingDecision(
                endpoint=EndpointKind.LOCAL,
                reason="remote unavailable and policy permits local fallback",
                crossed_boundary=False,
            )
            response = self.local.complete(request)

        latency_ms = (time.perf_counter() - start) * 1000.0
        cost = response.metadata.get("cost_usd")
        audit = ModelCallAudit(
            endpoint=decision.endpoint,
            reason=decision.reason,
            crossed_boundary=decision.crossed_boundary,
            fallback_used=fallback_used,
            quality_caveat=quality_caveat,
            prompt_sha256=hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
            prompt_chars=len(request.prompt),
            latency_ms=latency_ms,
            cost_usd=float(cost) if cost is not None else None,
        )
        return RoutedModelResult(response=response, audit=audit)


def _post_json_with_retries(
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    retries: int,
    retry_backoff_seconds: float,
    transport: httpx.BaseTransport | None,
) -> httpx.Response:
    attempts = retries + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(transport=transport, timeout=timeout) as client:
                response = client.post(url, json=payload, headers=headers)
            if response.status_code in {HTTPStatus.TOO_MANY_REQUESTS, *range(500, 600)} and attempt < attempts - 1:
                time.sleep(retry_backoff_seconds * (2**attempt))
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt >= attempts - 1:
                raise
            time.sleep(retry_backoff_seconds * (2**attempt))
    raise RuntimeError("unreachable retry state") from last_exc


def _extract_openai_response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str):
        return direct
    parts: list[str] = []
    for output in payload.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(str(content["text"]))
            elif content.get("type") == "refusal" and isinstance(content.get("refusal"), str):
                parts.append(str(content["refusal"]))
    return "\n".join(parts)
