# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Literal

from pydantic import Field

from solomon.api.schemas import SolomonModel

MCPTransportKind = Literal["stdio", "streamable-http"]


class MCPTransportConfig(SolomonModel):
    kind: MCPTransportKind = "stdio"
    host: str = "127.0.0.1"
    port: int = Field(default=8141, ge=1, le=65535)
    path: str = "/mcp"

    @property
    def url(self) -> str | None:
        if self.kind == "stdio":
            return None
        return f"http://{self.host}:{self.port}{self.path}"


__all__ = ["MCPTransportConfig", "MCPTransportKind"]
