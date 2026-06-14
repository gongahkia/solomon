# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from collections.abc import Mapping
from secrets import compare_digest

from solomon.api.schemas import SolomonModel


class MCPAuthConfig(SolomonModel):
    credential_env_var: str = "SOLOMON_MCP_TOKEN"
    require_http_token: bool = True


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
