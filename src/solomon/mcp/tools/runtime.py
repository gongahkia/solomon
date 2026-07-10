# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from solomon.api.service import SolomonService
from solomon.mcp.rate_limit import TokenBucketRateLimiter
from solomon.mcp.tools.audit import audit_pack as audit_pack_tool
from solomon.mcp.tools.helpers import _error_result, _log_mcp_call
from solomon.mcp.tools.read import (
    check_currency as check_currency_tool,
)
from solomon.mcp.tools.read import (
    dependency_suggestions as dependency_suggestions_tool,
)
from solomon.mcp.tools.read import (
    get_dependencies as get_dependencies_tool,
)
from solomon.mcp.tools.read import (
    impact as impact_tool,
)
from solomon.mcp.tools.read import (
    preflight_context as preflight_context_tool,
)
from solomon.mcp.tools.status import health as health_tool
from solomon.mcp.tools.write import ingest as ingest_tool
from solomon.mcp.tools.write import verify_position as verify_position_tool


class SolomonMCPRuntime:
    def __init__(self, service: SolomonService, rate_limiter: TokenBucketRateLimiter | None = None) -> None:
        self.service = service
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()

    def _rate_limit_error(self, tool_name: str, caller_id: str | None) -> dict[str, Any] | None:
        if self.rate_limiter.allow(caller_id):
            return None
        _log_mcp_call(
            self.service,
            tool_name,
            caller_id=caller_id,
            status="error",
            error_code="rate_limited",
        )
        return _error_result(
            "rate_limited",
            "MCP caller exceeded token-bucket rate limit",
            retryable=True,
            details={"caller_id": caller_id or "anonymous"},
        )

    def health(self, *, caller_id: str | None = None) -> dict[str, Any]:
        return health_tool(self, caller_id=caller_id)

    def preflight_context(
        self,
        *,
        query: str,
        matter_id: str | None = None,
        client_id: str | None = None,
        max_items: int = 5,
        max_context_tokens: int | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return preflight_context_tool(
            self,
            query=query,
            matter_id=matter_id,
            client_id=client_id,
            max_items=max_items,
            max_context_tokens=max_context_tokens,
            caller_id=caller_id,
        )

    def check_currency(
        self,
        *,
        knowledge_item_id: str,
        as_of: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return check_currency_tool(
            self,
            knowledge_item_id=knowledge_item_id,
            as_of=as_of,
            matter_id=matter_id,
            client_id=client_id,
            caller_id=caller_id,
        )

    def get_dependencies(
        self,
        *,
        knowledge_item_id: str,
        direction: str = "both",
        depth: int = 1,
        matter_id: str | None = None,
        client_id: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return get_dependencies_tool(
            self,
            knowledge_item_id=knowledge_item_id,
            direction=direction,
            depth=depth,
            matter_id=matter_id,
            client_id=client_id,
            caller_id=caller_id,
        )

    def verify_position(
        self,
        *,
        knowledge_item_id: str,
        verifier_id: str,
        decision: str,
        evidence_ref: str,
        successor_id: str | None = None,
        recorded_at: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return verify_position_tool(
            self,
            knowledge_item_id=knowledge_item_id,
            verifier_id=verifier_id,
            decision=decision,
            evidence_ref=evidence_ref,
            successor_id=successor_id,
            recorded_at=recorded_at,
            matter_id=matter_id,
            client_id=client_id,
            caller_id=caller_id,
        )

    def ingest(
        self,
        *,
        text: str,
        source_ref: str,
        scope: dict[str, Any],
        kind: str = "note",
        source_kind: str = "associate",
        author: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return ingest_tool(
            self,
            text=text,
            source_ref=source_ref,
            scope=scope,
            kind=kind,
            source_kind=source_kind,
            author=author,
            caller_id=caller_id,
        )

    def audit_pack(
        self,
        *,
        knowledge_item_id: str,
        format: str = "json",
        matter_id: str | None = None,
        client_id: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return audit_pack_tool(
            self,
            knowledge_item_id=knowledge_item_id,
            format=format,
            matter_id=matter_id,
            client_id=client_id,
            caller_id=caller_id,
        )

    def dependency_suggestions(
        self,
        *,
        knowledge_item_id: str,
        decision: str = "pending",
        limit: int = 100,
        matter_id: str | None = None,
        client_id: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return dependency_suggestions_tool(
            self,
            knowledge_item_id=knowledge_item_id,
            decision=decision,
            limit=limit,
            matter_id=matter_id,
            client_id=client_id,
            caller_id=caller_id,
        )

    def impact(
        self,
        *,
        external_authority_id: str,
        as_of: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return impact_tool(
            self,
            external_authority_id=external_authority_id,
            as_of=as_of,
            matter_id=matter_id,
            client_id=client_id,
            caller_id=caller_id,
        )
