# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

AuthRole = Literal["admin", "tenant"]

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

    def has_scope(self, required_scope: str) -> bool:
        return ADMIN_SCOPE in self.scopes or required_scope in self.scopes


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
