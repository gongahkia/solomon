# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from solomon.api.app import create_app
from solomon.config import Settings
from solomon.orchestrator.models import (
    EndpointKind,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    OpenAIResponsesEndpoint,
    RoutingPolicy,
)

pytestmark = pytest.mark.integration


def test_live_local_model_answer_path_uses_sanitized_boundary_prompt(tmp_path: Path) -> None:
    target_url = os.environ.get("SOLOMON_TEST_LOCAL_MODEL_URL")
    if not target_url:
        pytest.skip("set SOLOMON_TEST_LOCAL_MODEL_URL to run live local-model integration coverage")
    model_name = os.environ.get("SOLOMON_TEST_LOCAL_MODEL_NAME", "qwen2.5-coder:1.5b")
    with _CaptureProxy(target_url) as proxy:
        app = create_app(
            Settings(
                data_dir=tmp_path / "data",
                journal_dir=tmp_path / "journal",
                local_model_url=proxy.url,
                local_model_name=model_name,
                zero_egress_mode=True,
            )
        )

        async def exercise() -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=180) as client:
                created = await client.post(
                    "/ingest",
                    json={
                        "kind": "position",
                        "content": "Client A may rely on Regulation R section 12 for Structure X.",
                        "source_kind": "partner",
                        "source_ref": "memo-local-live",
                        "matter_id": "matter-local",
                        "client_id": "client-a",
                    },
                )
                answer = await client.post(
                    "/answer",
                    json={
                        "query": "Can Client A rely on Regulation R section 12?",
                        "matter_id": "matter-local",
                        "client_id": "client-a",
                        "matter_sensitivity": "strict",
                        "max_tokens": 192,
                    },
                )
                return created, answer

        created, answer = asyncio.run(exercise())

    assert created.status_code == 200
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["text"].strip()
    assert payload["model"]["endpoint"] == "local"
    assert payload["model"]["crossed_boundary"] is False
    assert payload["prompt"]["boundary_applied"] is True
    assert payload["recalled"][0]["item"]["id"] == created.json()["id"]
    assert proxy.payloads
    model_payload = proxy.payloads[-1]
    assert model_payload["model"] == model_name
    assert "Client A" not in model_payload["prompt"]
    assert "[CLIENT_1]" in model_payload["prompt"]


def test_remote_zdr_zero_egress_and_disabled_policy_block_remote() -> None:
    remote = _CountingOpenAIResponsesEndpoint(
        model="gpt-test",
        api_key="unused",
        url="http://127.0.0.1:9/v1/responses",
        retries=0,
        timeout=0.1,
    )
    local = _StaticEndpoint()
    zero = ModelRouter(
        remote=remote,
        local=local,
        policy=RoutingPolicy(remote_allowed=True, zero_egress_mode=True, fallback_to_local_on_remote_error=False),
    )
    blocked = zero.complete(ModelRequest(prompt="sanitized prompt"), matter=None)

    assert blocked.audit.endpoint is EndpointKind.LOCAL
    assert blocked.audit.crossed_boundary is False
    assert blocked.audit.reason == "zero-egress mode forces local endpoint"
    assert remote.calls == 0

    disabled = ModelRouter(
        remote=remote,
        local=_StaticEndpoint(),
        policy=RoutingPolicy(remote_allowed=False, zero_egress_mode=False, fallback_to_local_on_remote_error=False),
    )
    disabled_result = disabled.complete(ModelRequest(prompt="sanitized prompt"), matter=None)
    assert disabled_result.audit.endpoint is EndpointKind.LOCAL
    assert disabled_result.audit.reason == "remote endpoint disabled by policy"
    assert remote.calls == 0


def test_live_remote_zdr_answer_path_runs_when_explicitly_enabled(tmp_path: Path) -> None:
    url = os.environ.get("SOLOMON_TEST_REMOTE_ZDR_URL")
    key = os.environ.get("SOLOMON_TEST_REMOTE_ZDR_API_KEY")
    if not url or not key:
        pytest.skip("set SOLOMON_TEST_REMOTE_ZDR_URL and SOLOMON_TEST_REMOTE_ZDR_API_KEY for live remote ZDR coverage")
    model = os.environ.get("SOLOMON_TEST_REMOTE_ZDR_MODEL", "gpt-5.5")
    app = create_app(
        Settings(
            sku="server",
            server_api_key="test-server-key",
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            remote_model_url=url,
            remote_model_provider="openai-responses",
            remote_model_api_key=key,
            remote_model_name=model,
            allow_remote_egress=True,
            zero_egress_mode=False,
        )
    )

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        headers = {"x-api-key": "test-server-key", "x-tenant-id": "tenant-zdr-live"}
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=180) as client:
            created = await client.post(
                "/ingest",
                headers=headers,
                json={
                    "kind": "position",
                    "content": "Client A may rely on Regulation R section 12 for Structure X.",
                    "source_kind": "partner",
                    "source_ref": "memo-remote-live",
                    "matter_id": "matter-remote",
                    "client_id": "client-a",
                },
            )
            answer = await client.post(
                "/answer",
                headers=headers,
                json={
                    "query": "Can Client A rely on Regulation R section 12?",
                    "matter_id": "matter-remote",
                    "client_id": "client-a",
                    "matter_sensitivity": "standard",
                    "max_tokens": 64,
                },
            )
            return created, answer

    created, answer = asyncio.run(exercise())

    assert created.status_code == 200
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["text"].strip()
    assert payload["model"]["endpoint"] == "remote_zdr"
    assert payload["model"]["crossed_boundary"] is True
    assert payload["prompt"]["boundary_applied"] is True
    assert payload["recalled"][0]["item"]["id"] == created.json()["id"]


class _CaptureProxy:
    def __init__(self, target_url: str) -> None:
        self.target_url = target_url
        self.payloads: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _CaptureProxy:
        payloads = self.payloads
        target_url = self.target_url

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length).decode())
                payloads.append(payload)
                response = httpx.post(target_url, json=payload, timeout=180)
                self.send_response(response.status_code)
                self.send_header("content-type", response.headers.get("content-type", "application/json"))
                self.end_headers()
                self.wfile.write(response.content)

            def log_message(self, _format: str, *args: Any) -> None:
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("proxy not started")
        host_raw = self._server.server_address[0]
        host = host_raw.decode() if isinstance(host_raw, bytes) else str(host_raw)
        port = int(self._server.server_address[1])
        return f"http://{host}:{port}/api/generate"


class _StaticEndpoint:
    kind = EndpointKind.LOCAL

    def complete(self, _request: ModelRequest) -> ModelResponse:
        return ModelResponse(text="local answer", endpoint=self.kind)


class _CountingOpenAIResponsesEndpoint(OpenAIResponsesEndpoint):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return super().complete(request)
