# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest

from solomon.currency.models import Matter
from solomon.orchestrator.models import (
    EndpointKind,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    OpenAIResponsesEndpoint,
    RoutingPolicy,
)


@dataclass
class FakeEndpoint:
    kind: EndpointKind
    text: str
    fail: bool = False
    calls: int = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError("endpoint down")
        return ModelResponse(text=self.text, endpoint=self.kind, metadata={"cost_usd": 0.01})


def _matter(sensitivity: str) -> Matter:
    return Matter(id=f"matter-{sensitivity}", client_id="client-1", name="Matter", sensitivity=sensitivity)  # type: ignore[arg-type]


def test_standard_matter_routes_to_remote_zdr_with_metadata_only_audit() -> None:
    remote = FakeEndpoint(EndpointKind.REMOTE_ZDR, "remote answer")
    local = FakeEndpoint(EndpointKind.LOCAL, "local answer")
    router = ModelRouter(remote=remote, local=local)

    result = router.complete(ModelRequest(prompt="sanitized prompt"), matter=_matter("standard"))

    assert result.response.text == "remote answer"
    assert result.audit.endpoint is EndpointKind.REMOTE_ZDR
    assert result.audit.crossed_boundary is True
    assert result.audit.prompt_chars == len("sanitized prompt")
    assert result.audit.prompt_sha256 != "sanitized prompt"
    assert result.audit.cost_usd == 0.01
    assert remote.calls == 1
    assert local.calls == 0


def test_strict_matter_and_zero_egress_force_local() -> None:
    remote = FakeEndpoint(EndpointKind.REMOTE_ZDR, "remote answer")
    local = FakeEndpoint(EndpointKind.LOCAL, "local answer")
    router = ModelRouter(remote=remote, local=local)
    zero = ModelRouter(remote=remote, local=local, policy=RoutingPolicy(zero_egress_mode=True))

    strict_result = router.complete(ModelRequest(prompt="sanitized prompt"), matter=_matter("strict"))
    zero_result = zero.complete(ModelRequest(prompt="sanitized prompt"), matter=_matter("standard"))

    assert strict_result.audit.endpoint is EndpointKind.LOCAL
    assert strict_result.audit.crossed_boundary is False
    assert zero_result.audit.reason == "zero-egress mode forces local endpoint"


def test_remote_failure_falls_back_to_local_when_allowed() -> None:
    remote = FakeEndpoint(EndpointKind.REMOTE_ZDR, "remote answer", fail=True)
    local = FakeEndpoint(EndpointKind.LOCAL, "local answer")
    router = ModelRouter(remote=remote, local=local)

    result = router.complete(ModelRequest(prompt="sanitized prompt"), matter=_matter("standard"))

    assert result.response.text == "local answer"
    assert result.audit.fallback_used is True
    assert result.audit.quality_caveat == "remote endpoint unavailable; local model fallback used"
    assert result.audit.crossed_boundary is False


def test_remote_failure_can_fail_closed_without_fallback() -> None:
    remote = FakeEndpoint(EndpointKind.REMOTE_ZDR, "remote answer", fail=True)
    local = FakeEndpoint(EndpointKind.LOCAL, "local answer")
    router = ModelRouter(
        remote=remote,
        local=local,
        policy=RoutingPolicy(fallback_to_local_on_remote_error=False),
    )

    with pytest.raises(RuntimeError, match="endpoint down"):
        router.complete(ModelRequest(prompt="sanitized prompt"), matter=_matter("standard"))


def test_openai_responses_endpoint_posts_provider_payload_and_extracts_output_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert request.url.path == "/v1/responses"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert payload == {
            "model": "gpt-test",
            "input": "sanitized prompt",
            "max_output_tokens": 128,
            "temperature": 0.0,
        }
        return httpx.Response(
            200,
            json={
                "id": "resp-1",
                "model": "gpt-test",
                "output_text": "provider answer",
                "usage": {"input_tokens": 4, "output_tokens": 2},
            },
        )

    endpoint = OpenAIResponsesEndpoint(
        model="gpt-test",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    response = endpoint.complete(ModelRequest(prompt="sanitized prompt", max_tokens=128))

    assert response.text == "provider answer"
    assert response.metadata["provider"] == "openai-responses"
    assert response.metadata["response_id"] == "resp-1"


def test_openai_responses_endpoint_retries_transient_errors_and_parses_nested_output() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "transient"})
        return httpx.Response(
            200,
            json={
                "id": "resp-2",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "retried answer"}],
                    }
                ],
            },
        )

    endpoint = OpenAIResponsesEndpoint(
        model="gpt-test",
        api_key="test-key",
        retries=1,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    response = endpoint.complete(ModelRequest(prompt="sanitized prompt"))

    assert calls == 2
    assert response.text == "retried answer"
