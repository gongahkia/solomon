# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from secrets import compare_digest
from urllib.parse import urlparse

from pydantic import Field, field_validator

from solomon.api.auth import AuthRole
from solomon.api.schemas import SolomonModel

MCP_ADMIN_SCOPE = "solomon.admin"
MCP_READ_SCOPE = "solomon.read"
MCP_WRITE_SCOPE = "solomon.write"
MCP_AUDIT_SCOPE = "solomon.audit"
MCP_KNOWN_SCOPES = frozenset({MCP_ADMIN_SCOPE, MCP_READ_SCOPE, MCP_WRITE_SCOPE, MCP_AUDIT_SCOPE})


class MCPPrincipal(SolomonModel):
    subject: str = Field(min_length=1, max_length=256)
    role: AuthRole
    roles: frozenset[AuthRole] = Field(default_factory=frozenset)
    scopes: frozenset[str] = Field(default_factory=frozenset)
    matter_ids: frozenset[str] = Field(default_factory=lambda: frozenset({"*"}))
    client_ids: frozenset[str] = Field(default_factory=lambda: frozenset({"*"}))

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: frozenset[str]) -> frozenset[str]:
        unknown = sorted(values - MCP_KNOWN_SCOPES)
        if unknown:
            raise ValueError(f"unknown MCP scopes: {', '.join(unknown)}")
        return values

    @field_validator("matter_ids", "client_ids")
    @classmethod
    def validate_scope_ids(cls, values: frozenset[str]) -> frozenset[str]:
        if not values or any(not value for value in values):
            raise ValueError("MCP scope IDs must be non-empty")
        if "*" in values and len(values) > 1:
            raise ValueError("MCP wildcard scope cannot be combined with explicit IDs")
        return values

    def has_scope(self, required_scope: str) -> bool:
        return MCP_ADMIN_SCOPE in self.scopes or required_scope in self.scopes

    def has_role(self, role: AuthRole) -> bool:
        return self.role == role or role in self.roles

    def permits_scope(self, *, matter_id: str | None, client_id: str | None) -> bool:
        return _scope_allows(self.matter_ids, matter_id) and _scope_allows(self.client_ids, client_id)

    @property
    def has_restricted_scope(self) -> bool:
        return self.matter_ids != {"*"} or self.client_ids != {"*"}


@dataclass(frozen=True)
class MCPCallContext:
    principal: MCPPrincipal | None
    correlation_id: str


_mcp_call_context: ContextVar[MCPCallContext | None] = ContextVar("mcp_call_context", default=None)


@contextmanager
def authorized_mcp_call(principal: MCPPrincipal | None, correlation_id: str) -> Iterator[None]:
    token = _mcp_call_context.set(MCPCallContext(principal=principal, correlation_id=correlation_id))
    try:
        yield
    finally:
        _mcp_call_context.reset(token)


def current_mcp_call() -> MCPCallContext | None:
    return _mcp_call_context.get()


class MCPAuthConfig(SolomonModel):
    credential_env_var: str = "SOLOMON_MCP_TOKEN"
    require_http_token: bool = True
    authorization_servers: tuple[str, ...] = Field(default_factory=tuple)
    scopes: tuple[str, ...] = Field(default_factory=tuple)
    resource_name: str = "Solomon MCP"
    static_principal: MCPPrincipal | None = None
    require_identity: bool = False

    @field_validator("authorization_servers")
    @classmethod
    def validate_authorization_servers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError("authorization server URLs must be absolute https URLs without query or fragment")
        return values

    @field_validator("scopes")
    @classmethod
    def validate_advertised_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(values) - MCP_KNOWN_SCOPES)
        if unknown:
            raise ValueError(f"unknown MCP scopes: {', '.join(unknown)}")
        return values

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MCPAuthConfig:
        resolved_env = env or os.environ
        raw_principal = resolved_env.get("SOLOMON_MCP_PRINCIPAL_JSON")
        principal = MCPPrincipal.model_validate_json(raw_principal) if raw_principal else None
        return cls(
            static_principal=principal,
            require_identity=_env_bool(resolved_env.get("SOLOMON_MCP_REQUIRE_IDENTITY")),
        )

    def resolved_static_principal(self) -> MCPPrincipal:
        return self.static_principal or MCPPrincipal(
            subject="mcp-static",
            role="admin",
            scopes=frozenset(self.scopes) or frozenset({MCP_READ_SCOPE}),
        )


def token_from_env(config: MCPAuthConfig | None = None, env: Mapping[str, str] | None = None) -> str | None:
    resolved_config = config or MCPAuthConfig()
    resolved_env = env or os.environ
    return resolved_env.get(resolved_config.credential_env_var)


def bearer_token_matches(supplied_token: str | None, expected_token: str | None) -> bool:
    if expected_token is None:
        return True
    if supplied_token is None:
        return False
    return compare_digest(supplied_token, expected_token)


def _scope_allows(allowed: frozenset[str], value: str | None) -> bool:
    return "*" in allowed or value is not None and value in allowed


def _env_bool(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("SOLOMON_MCP_REQUIRE_IDENTITY must be true or false")


__all__ = [
    "MCP_ADMIN_SCOPE",
    "MCP_AUDIT_SCOPE",
    "MCP_KNOWN_SCOPES",
    "MCP_READ_SCOPE",
    "MCP_WRITE_SCOPE",
    "MCPAuthConfig",
    "MCPCallContext",
    "MCPPrincipal",
    "authorized_mcp_call",
    "bearer_token_matches",
    "current_mcp_call",
    "token_from_env",
]
