# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from solomon import __version__
from solomon.boundary.solomon import probe_boundary_client
from solomon.mcp.tools.helpers import _log_mcp_call

if TYPE_CHECKING:
    from solomon.mcp.tools.runtime import SolomonMCPRuntime


def health(runtime: SolomonMCPRuntime, *, caller_id: str | None = None) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.health", caller_id)
    if limited is not None:
        return limited
    items = runtime.service.store.get_many()
    journal = runtime.service.audit.verify().model_dump(mode="json")
    boundary = probe_boundary_client().model_dump(mode="json")
    _log_mcp_call(
        runtime.service,
        "solomon.health",
        caller_id=caller_id,
        input_payload={},
        metadata={"item_count": len(items)},
    )
    return {
        "version": __version__,
        "store": {"ok": True, "item_count": len(items)},
        "journal": journal,
        "boundary": boundary,
    }
