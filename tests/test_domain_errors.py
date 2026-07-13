# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from solomon.api.app import create_app
from solomon.client import SolomonAPIError, SolomonClient
from solomon.config import Settings
from solomon.errors import (
    BadRequestError,
    ConflictError,
    ErrorCategory,
    NotFoundError,
    PolicyRefusalError,
    UpstreamError,
    domain_error_from_exception,
)
from solomon.mcp.tools.helpers import _exception_error_result


def test_typed_domain_errors_have_stable_codes_categories_and_retryability() -> None:
    assert BadRequestError("bad input").error_payload()["category"] == ErrorCategory.VALIDATION.value
    assert NotFoundError("missing").error_payload()["code"] == "not_found"
    assert PolicyRefusalError("denied").error_payload()["category"] == ErrorCategory.AUTHORIZATION.value
    assert ConflictError("conflict").status_code == 409
    assert UpstreamError("unavailable").error_payload()["retryable"] is True
    assert isinstance(domain_error_from_exception(ConnectionError("down")), UpstreamError)
    assert isinstance(domain_error_from_exception(KeyError("missing")), NotFoundError)


def test_http_validation_and_domain_errors_use_structured_envelopes(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal"))

    async def call() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            validation = await client.post("/ingest", json={})
            missing = await client.post(
                "/review-tasks/missing/assign",
                json={"reviewer_id": "lawyer-a", "assigned_by": "curator-a"},
            )
            return validation, missing

    validation, missing = asyncio.run(call())

    assert validation.status_code == 422
    assert validation.json()["error"] == {
        "category": "validation",
        "code": "validation_failed",
        "message": "request validation failed",
        "retryable": False,
        "details": {},
    }
    assert missing.status_code == 404
    assert missing.json()["error"]["category"] == "state"
    assert missing.json()["error"]["code"] == "not_found"
    assert missing.json()["error"]["retryable"] is False


def test_mcp_and_sdk_preserve_machine_readable_domain_errors() -> None:
    assert _exception_error_result(ConflictError("task already resolved"))["error"] == {
        "category": "state",
        "code": "invalid_state",
        "message": "MCP tool request conflicts with current state",
        "retryable": False,
        "details": {},
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "error": {
                    "category": "upstream",
                    "code": "upstream_failure",
                    "message": "authority connector unavailable",
                    "retryable": True,
                    "details": {},
                }
            },
        )

    with SolomonClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SolomonAPIError) as exc_info:
            client.recall({"query": "authority"})

    error = exc_info.value
    assert error.status_code == 503
    assert error.code == "upstream_failure"
    assert error.category == "upstream"
    assert error.retryable is True
    assert str(error) == "authority connector unavailable"
