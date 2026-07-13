# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from solomon.api.auth import AuthPrincipal, AuthRole, scopes_for_roles
from solomon.api.service import SolomonService
from solomon.mcp.auth import (
    MCP_AUDIT_SCOPE,
    MCP_READ_SCOPE,
    MCP_WRITE_SCOPE,
    MCPPrincipal,
    authorized_mcp_call,
    current_mcp_call,
)
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
from solomon.mcp.tools.read import (
    verification_queue as verification_queue_tool,
)
from solomon.mcp.tools.report import currency_report as currency_report_tool
from solomon.mcp.tools.status import health as health_tool
from solomon.mcp.tools.write import ingest as ingest_tool
from solomon.mcp.tools.write import verify_position as verify_position_tool
from solomon.store.sqlite import ItemNotFoundError


@dataclass(frozen=True)
class MCPToolPermission:
    required_scope: str
    allowed_roles: frozenset[AuthRole]


_READ_ROLES: frozenset[AuthRole] = frozenset({"admin", "curator", "reviewer", "lawyer", "integration", "tenant"})
_WRITE_ROLES: frozenset[AuthRole] = frozenset({"admin", "curator", "reviewer", "lawyer", "tenant"})
_REVIEW_ROLES: frozenset[AuthRole] = frozenset({"admin", "reviewer", "lawyer"})

MCP_TOOL_PERMISSIONS: dict[str, MCPToolPermission] = {
    "solomon.health": MCPToolPermission(MCP_READ_SCOPE, _READ_ROLES),
    "solomon.preflight_context": MCPToolPermission(MCP_READ_SCOPE, _READ_ROLES),
    "solomon.check_currency": MCPToolPermission(MCP_READ_SCOPE, _READ_ROLES),
    "solomon.get_dependencies": MCPToolPermission(MCP_READ_SCOPE, _READ_ROLES),
    "solomon.verification_queue": MCPToolPermission(MCP_READ_SCOPE, _REVIEW_ROLES),
    "solomon.audit_pack": MCPToolPermission(MCP_AUDIT_SCOPE, _REVIEW_ROLES),
    "solomon.currency_report": MCPToolPermission(MCP_READ_SCOPE, _READ_ROLES),
    "solomon.dependency_suggestions": MCPToolPermission(MCP_READ_SCOPE, _READ_ROLES),
    "solomon.impact": MCPToolPermission(MCP_READ_SCOPE, _READ_ROLES),
    "solomon.ingest": MCPToolPermission(MCP_WRITE_SCOPE, _WRITE_ROLES),
    "solomon.verify_position": MCPToolPermission(MCP_WRITE_SCOPE, _REVIEW_ROLES),
}


class SolomonMCPRuntime:
    def __init__(
        self,
        service: SolomonService,
        rate_limiter: TokenBucketRateLimiter | None = None,
        *,
        principal: MCPPrincipal | None = None,
        require_identity: bool = False,
    ) -> None:
        self.service = service
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()
        self.principal = principal
        self.require_identity = require_identity

    def _invoke(
        self,
        tool_name: str,
        handler: Callable[[str | None], dict[str, Any]],
        *,
        caller_id: str | None,
        matter_id: str | None = None,
        client_id: str | None = None,
        knowledge_item_id: str | None = None,
        requires_global_scope: bool = False,
    ) -> dict[str, Any]:
        principal = self._principal()
        correlation_id = f"mcp:{uuid.uuid4().hex}"
        with (
            self.service.telemetry.span(
                "solomon.mcp.tool",
                attributes={"solomon.mcp.tool": tool_name},
            ),
            authorized_mcp_call(principal, correlation_id),
        ):
            denial = self._authorization_error(
                tool_name,
                principal=principal,
                matter_id=matter_id,
                client_id=client_id,
                knowledge_item_id=knowledge_item_id,
                requires_global_scope=requires_global_scope,
            )
            if denial is not None:
                _log_mcp_call(
                    self.service,
                    tool_name,
                    caller_id=caller_id,
                    matter_id=matter_id,
                    client_id=client_id,
                    status="error",
                    error_code=denial["error"]["code"],
                    metadata={"authorization": "denied"},
                )
                return denial
            effective_caller_id = principal.subject if principal is not None else caller_id
            service_context = self._service_context(principal, correlation_id)
            with service_context:
                return handler(effective_caller_id)

    def _principal(self) -> MCPPrincipal | None:
        context = current_mcp_call()
        if context is not None and context.principal is not None:
            return context.principal
        return self.principal

    def _authorization_error(
        self,
        tool_name: str,
        *,
        principal: MCPPrincipal | None,
        matter_id: str | None,
        client_id: str | None,
        knowledge_item_id: str | None,
        requires_global_scope: bool,
    ) -> dict[str, Any] | None:
        if principal is None:
            if self.require_identity:
                return _authorization_error(tool_name, "authenticated MCP identity is required")
            return None
        permission = MCP_TOOL_PERMISSIONS[tool_name]
        if not principal.has_scope(permission.required_scope):
            return _authorization_error(tool_name, "MCP scope is not permitted")
        if not any(principal.has_role(role) for role in permission.allowed_roles):
            return _authorization_error(tool_name, "MCP role is not permitted")
        if requires_global_scope and principal.has_restricted_scope:
            return _authorization_error(tool_name, "tool requires unrestricted matter and client scope")
        if knowledge_item_id is not None:
            try:
                item = self.service.store.get_item(knowledge_item_id)
            except ItemNotFoundError:
                return None
            if not principal.permits_scope(matter_id=item.matter_id, client_id=item.client_id):
                return _authorization_error(tool_name, "knowledge item scope is not permitted")
        if principal.has_restricted_scope and not principal.permits_scope(matter_id=matter_id, client_id=client_id):
            return _authorization_error(tool_name, "explicit permitted matter and client scope is required")
        return None

    def _service_context(self, principal: MCPPrincipal | None, correlation_id: str) -> Any:
        if principal is None:
            return nullcontext()
        roles = frozenset({principal.role, *principal.roles})
        return self.service.authorized_as(
            AuthPrincipal(
                subject=principal.subject,
                role=principal.role,
                tenant_id=None,
                scopes=scopes_for_roles(roles),
                roles=roles,
            ),
            correlation_id,
        )

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
        return self._invoke("solomon.health", lambda caller: health_tool(self, caller_id=caller), caller_id=caller_id)

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
        return self._invoke(
            "solomon.preflight_context",
            lambda caller: preflight_context_tool(
                self,
                query=query,
                matter_id=matter_id,
                client_id=client_id,
                max_items=max_items,
                max_context_tokens=max_context_tokens,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
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
        return self._invoke(
            "solomon.check_currency",
            lambda caller: check_currency_tool(
                self,
                knowledge_item_id=knowledge_item_id,
                as_of=as_of,
                matter_id=matter_id,
                client_id=client_id,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            knowledge_item_id=knowledge_item_id,
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
        return self._invoke(
            "solomon.get_dependencies",
            lambda caller: get_dependencies_tool(
                self,
                knowledge_item_id=knowledge_item_id,
                direction=direction,
                depth=depth,
                matter_id=matter_id,
                client_id=client_id,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            knowledge_item_id=knowledge_item_id,
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
        return self._invoke(
            "solomon.verify_position",
            lambda caller: verify_position_tool(
                self,
                knowledge_item_id=knowledge_item_id,
                verifier_id=verifier_id,
                decision=decision,
                evidence_ref=evidence_ref,
                successor_id=successor_id,
                recorded_at=recorded_at,
                matter_id=matter_id,
                client_id=client_id,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            knowledge_item_id=knowledge_item_id,
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
        matter_id = scope.get("matter_id") if isinstance(scope.get("matter_id"), str) else None
        client_id = scope.get("client_id") if isinstance(scope.get("client_id"), str) else None
        return self._invoke(
            "solomon.ingest",
            lambda caller: ingest_tool(
                self,
                text=text,
                source_ref=source_ref,
                scope=scope,
                kind=kind,
                source_kind=source_kind,
                author=author,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
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
        return self._invoke(
            "solomon.audit_pack",
            lambda caller: audit_pack_tool(
                self,
                knowledge_item_id=knowledge_item_id,
                format=format,
                matter_id=matter_id,
                client_id=client_id,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            knowledge_item_id=knowledge_item_id,
            requires_global_scope=True,
        )

    def currency_report(
        self,
        *,
        period_start: str,
        period_end: str,
        scope: str = "firm",
        practice_area: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        format: str = "json",
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            "solomon.currency_report",
            lambda caller: currency_report_tool(
                self,
                period_start=period_start,
                period_end=period_end,
                scope=scope,
                practice_area=practice_area,
                matter_id=matter_id,
                client_id=client_id,
                format=format,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            requires_global_scope=scope != "matter",
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
        return self._invoke(
            "solomon.dependency_suggestions",
            lambda caller: dependency_suggestions_tool(
                self,
                knowledge_item_id=knowledge_item_id,
                decision=decision,
                limit=limit,
                matter_id=matter_id,
                client_id=client_id,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            knowledge_item_id=knowledge_item_id,
        )

    def verification_queue(
        self,
        *,
        reviewer_id: str | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
        caller_id: str | None = None,
    ) -> dict[str, Any]:
        return self._invoke(
            "solomon.verification_queue",
            lambda caller: verification_queue_tool(
                self,
                reviewer_id=reviewer_id,
                matter_id=matter_id,
                client_id=client_id,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
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
        return self._invoke(
            "solomon.impact",
            lambda caller: impact_tool(
                self,
                external_authority_id=external_authority_id,
                as_of=as_of,
                matter_id=matter_id,
                client_id=client_id,
                caller_id=caller,
            ),
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
        )


def _authorization_error(tool_name: str, reason: str) -> dict[str, Any]:
    return _error_result(
        "authorization_denied",
        "MCP tool request was denied",
        retryable=False,
        details={"tool_name": tool_name, "reason": reason},
    )
