# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import time
from enum import Enum
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

    def __init__(self, *, url: str, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, request: ModelRequest) -> ModelResponse:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            self.url,
            json=request.model_dump(mode="json"),
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return ModelResponse(
            text=str(payload.get("text", payload.get("response", ""))),
            endpoint=self.kind,
            metadata={k: v for k, v in payload.items() if k not in {"text", "response"}},
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

