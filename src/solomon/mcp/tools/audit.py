# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from solomon.mcp.tools.helpers import _append_mcp_call, _mcp_log_payload, _scope_error_for_item

if TYPE_CHECKING:
    from solomon.mcp.tools.runtime import SolomonMCPRuntime


def audit_pack(
    runtime: SolomonMCPRuntime,
    *,
    knowledge_item_id: str,
    format: str = "json",
    matter_id: str | None = None,
    client_id: str | None = None,
    caller_id: str | None = None,
) -> dict[str, Any]:
    limited = runtime._rate_limit_error("solomon.audit_pack", caller_id)
    if limited is not None:
        return limited
    scope_error = _scope_error_for_item(
        runtime.service,
        knowledge_item_id,
        matter_id=matter_id,
        client_id=client_id,
        caller_id=caller_id,
    )
    if scope_error is not None:
        return scope_error
    _ = runtime.service.why(knowledge_item_id)
    with TemporaryDirectory(prefix="solomon-mcp-audit-") as temp_dir:
        pack_dir = runtime.service.export_audit_pack(Path(temp_dir))
        manifest = (pack_dir / "manifest.json").read_text(encoding="utf-8")
    entry = _append_mcp_call(
        runtime.service,
        _mcp_log_payload(
            "solomon.audit_pack",
            caller_id=caller_id,
            matter_id=matter_id,
            client_id=client_id,
            input_payload={"knowledge_item_id": knowledge_item_id, "format": format},
        ),
    )
    return {
        "knowledge_item_id": knowledge_item_id,
        "format": format,
        "pack": manifest if format == "pdf" else {"manifest_json": manifest},
        "hash_chain": {"entry_hash": entry.entry_hash},
    }
