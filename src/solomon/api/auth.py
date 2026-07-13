# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

AuthRole = Literal["admin", "curator", "reviewer", "lawyer", "integration", "tenant"]

ADMIN_SCOPE = "admin:*"
TENANT_READ_SCOPE = "tenant:read"
TENANT_WRITE_SCOPE = "tenant:write"
TENANT_MANAGE_SCOPE = "tenant:manage"
SOURCE_MANAGE_SCOPE = "source:manage"
DIAGNOSTICS_READ_SCOPE = "diagnostics:read"

KNOWN_AUTH_SCOPES = frozenset(
    {
        ADMIN_SCOPE,
        TENANT_READ_SCOPE,
        TENANT_WRITE_SCOPE,
        TENANT_MANAGE_SCOPE,
        SOURCE_MANAGE_SCOPE,
        DIAGNOSTICS_READ_SCOPE,
    }
)
ADMIN_AUTH_SCOPES = frozenset(KNOWN_AUTH_SCOPES)
DEFAULT_TENANT_SCOPES = (TENANT_READ_SCOPE, TENANT_WRITE_SCOPE)
OIDC_AUTH_ROLES: frozenset[AuthRole] = frozenset({"admin", "curator", "reviewer", "lawyer", "integration"})
ROLE_PRECEDENCE: tuple[AuthRole, ...] = ("admin", "curator", "reviewer", "lawyer", "integration", "tenant")
ROLE_SCOPES: dict[AuthRole, frozenset[str]] = {
    "admin": ADMIN_AUTH_SCOPES,
    "curator": frozenset({TENANT_READ_SCOPE, TENANT_WRITE_SCOPE, SOURCE_MANAGE_SCOPE}),
    "reviewer": frozenset(DEFAULT_TENANT_SCOPES),
    "lawyer": frozenset(DEFAULT_TENANT_SCOPES),
    "integration": frozenset({TENANT_READ_SCOPE}),
    "tenant": frozenset(DEFAULT_TENANT_SCOPES),
}

_TENANT_READ_POST_PATHS = {
    "/answer",
    "/recall",
    "/references/extract",
    "/staleness/predict",
    "/timeline",
}


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    role: AuthRole
    tenant_id: str | None
    scopes: frozenset[str]
    roles: frozenset[AuthRole] = field(default_factory=frozenset)

    def has_scope(self, required_scope: str) -> bool:
        return ADMIN_SCOPE in self.scopes or required_scope in self.scopes

    def has_role(self, role: AuthRole) -> bool:
        return self.role == role or role in self.roles


def mapped_oidc_roles(
    claims: Mapping[str, Any],
    *,
    claim_name: str,
    mappings: Mapping[str, str],
) -> frozenset[AuthRole]:
    raw_roles = claims.get(claim_name)
    if isinstance(raw_roles, str):
        claim_roles = (raw_roles,)
    elif isinstance(raw_roles, list) and all(isinstance(role, str) for role in raw_roles):
        claim_roles = tuple(raw_roles)
    else:
        return frozenset()
    return frozenset(
        mapped_role
        for claim_role in claim_roles
        if (mapped_role := mappings.get(claim_role)) in OIDC_AUTH_ROLES
    )


def primary_role(roles: frozenset[AuthRole]) -> AuthRole:
    for role in ROLE_PRECEDENCE:
        if role in roles:
            return role
    raise ValueError("at least one role is required")


def scopes_for_roles(roles: frozenset[AuthRole]) -> frozenset[str]:
    return frozenset(scope for role in roles for scope in ROLE_SCOPES[role])


def extract_api_key(headers: Mapping[str, str]) -> str | None:
    api_key = headers.get("x-api-key")
    if api_key:
        return api_key
    authorization = headers.get("authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def required_scope_for_request(method: str, path: str) -> str:
    if path == "/diagnostics":
        return DIAGNOSTICS_READ_SCOPE
    if path == "/tenants" or path.startswith("/tenants/"):
        return TENANT_MANAGE_SCOPE
    if path == "/sources" and method.upper() == "POST":
        return SOURCE_MANAGE_SCOPE
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return TENANT_READ_SCOPE
    if path in _TENANT_READ_POST_PATHS:
        return TENANT_READ_SCOPE
    return TENANT_WRITE_SCOPE


def validate_auth_scopes(scopes: list[str]) -> list[str]:
    unknown = sorted(set(scopes) - KNOWN_AUTH_SCOPES)
    if unknown:
        raise ValueError(f"unknown auth scopes: {', '.join(unknown)}")
    return list(dict.fromkeys(scopes))


def static_secret_matches(expected: str | None, supplied: str | None) -> bool:
    if expected is None or supplied is None:
        return False
    return hmac.compare_digest(supplied, expected)
