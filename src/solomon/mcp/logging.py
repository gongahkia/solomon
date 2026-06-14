# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from solomon.api.schemas import SolomonModel

MCPCallStatus = Literal["ok", "error"]


class MCPCallLogRecord(SolomonModel):
    tool_name: str
    input_sha256: str
    status: MCPCallStatus
    caller_id: str | None = None
    matter_id: str | None = None
    client_id: str | None = None
    currency_outcome: str | None = None
    boundary_outcome: str | None = None
    error_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def hash_mcp_input(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["MCPCallLogRecord", "MCPCallStatus", "hash_mcp_input"]
