# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from collections.abc import Mapping
from secrets import compare_digest
from urllib.parse import urlparse

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel


class MCPAuthConfig(SolomonModel):
    credential_env_var: str = "SOLOMON_MCP_TOKEN"
    require_http_token: bool = True
    authorization_servers: tuple[str, ...] = Field(default_factory=tuple)
    scopes: tuple[str, ...] = Field(default_factory=tuple)
    resource_name: str = "Solomon MCP"

    @field_validator("authorization_servers")
    @classmethod
    def validate_authorization_servers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError("authorization server URLs must be absolute https URLs without query or fragment")
        return values


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


__all__ = ["MCPAuthConfig", "bearer_token_matches", "token_from_env"]
