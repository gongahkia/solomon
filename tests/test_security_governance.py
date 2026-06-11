# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

from solomon.api.app import create_app
from solomon.boundary.kaypoh import KaypohBoundary
from solomon.config import Settings


class HygieneKaypohClient:
    def __init__(self) -> None:
        self.pseudonymize_requests: list[dict[str, Any]] = []

    def review(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"classification": "SAFE", "findings": []}

    def pseudonymize(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.pseudonymize_requests.append(dict(kwargs["request"]))
        return {
            "pseudonymized_text": "Send [PERSON_1] the memo.",
            "mapping": [{"placeholder": "[PERSON_1]", "original_text": "Jane"}],
            "document_hash": "c" * 64,
        }

    def reidentify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"reidentified_text": "Send Jane the memo.", "replacement_count": 1}

    def scrub_document(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"document_base64": kwargs["document_base64"]}


def test_server_api_key_middleware_is_configured(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            sku="server",
            zero_egress_mode=False,
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            server_api_key="secret",
        )
    )

    middleware_names = [str(middleware.cls) for middleware in app.user_middleware]

    assert any("BaseHTTPMiddleware" in name for name in middleware_names)


def test_boundary_mapping_hygiene_never_persists_after_demasking() -> None:
    client = HygieneKaypohClient()
    boundary = KaypohBoundary(client)

    sanitized = boundary.sanitize_context("Send Jane the memo.", matter_id="matter-1")
    assert boundary.volatile_mapping_count() == 1
    assert client.pseudonymize_requests[0]["persist_mapping"] is False

    boundary.reidentify_response(sanitized.context_id, sanitized.sanitized_text)

    assert boundary.volatile_mapping_count() == 0
