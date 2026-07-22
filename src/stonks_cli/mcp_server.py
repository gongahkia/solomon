from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from stonks_cli.config import disable_provider, enable_provider, load_profile, save_profile
from stonks_cli.ledger import import_csv, list_events
from stonks_cli.storage import EncryptedLedger, export_backup

_MCP_TOOL_ALLOWLIST = frozenset(
    {
        "confirm_csv_import",
        "confirm_profile_backup",
        "confirm_provider_change",
        "prepare_csv_import",
        "prepare_profile_backup",
        "prepare_provider_change",
        "profile_status",
    }
)
_MCP_PREPARABLE_ACTIONS = frozenset({"csv_import", "profile_backup", "provider_change"})


@dataclass(frozen=True)
class PendingAction:
    profile: str
    action: str
    payload: dict[str, str]
    expires_at: datetime


def create_server() -> FastMCP:
    server = FastMCP("stonks-cli")
    pending: dict[str, PendingAction] = {}

    def prepare(profile: str, action: str, payload: dict[str, str]) -> dict[str, object]:
        if action not in _MCP_PREPARABLE_ACTIONS:
            raise ValueError("MCP action is prohibited")
        load_profile(profile)
        confirmation_id = uuid4().hex
        expires_at = datetime.now(UTC) + timedelta(minutes=5)
        pending[confirmation_id] = PendingAction(profile, action, payload, expires_at)
        return {
            "confirmation_id": confirmation_id,
            "profile": profile,
            "action": action,
            "expires_at": expires_at.isoformat(),
            "execution": "denied",
        }

    def consume(confirmation_id: str, action: str) -> PendingAction:
        request = pending.pop(confirmation_id, None)
        if request is None or request.expires_at <= datetime.now(UTC) or request.action != action:
            raise ValueError("confirmation is invalid or expired")
        return request

    @server.tool()
    def profile_status(profile: str, key_file: str | None = None) -> dict[str, object]:
        """Read encrypted profile status. It cannot trade or unlock broker accounts."""
        config = load_profile(profile)
        if key_file is not None:
            from dataclasses import replace

            config = replace(config, key_file=str(Path(key_file).expanduser().resolve()))
        return {
            "profile": config.name,
            "event_count": len(list_events(EncryptedLedger(config))),
            "execution": "denied",
        }

    @server.tool()
    def prepare_csv_import(profile: str, path: str) -> dict[str, object]:
        """Prepare, but do not execute, a local CSV import. Confirm once within five minutes."""
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("CSV import path must be an existing regular file")
        response = prepare(profile, "csv_import", {"path": str(source)})
        response["path"] = str(source)
        return response

    @server.tool()
    def confirm_csv_import(confirmation_id: str) -> dict[str, object]:
        """Execute one prepared CSV import. Confirmation IDs are single-use and expire after five minutes."""
        request = consume(confirmation_id, "csv_import")
        config = load_profile(request.profile)
        inserted, skipped, source_hash = import_csv(
            EncryptedLedger(config), Path(request.payload["path"])
        )
        return {
            "profile": request.profile,
            "inserted": inserted,
            "skipped": skipped,
            "source_hash": source_hash,
            "execution": "denied",
        }

    @server.tool()
    def prepare_provider_change(profile: str, provider_id: str, enabled: bool) -> dict[str, object]:
        """Prepare one local provider configuration change. Confirm once within five minutes."""
        response = prepare(
            profile,
            "provider_change",
            {"enabled": str(enabled), "provider_id": provider_id.strip().lower()},
        )
        response["provider_id"] = provider_id.strip().lower()
        response["enabled"] = enabled
        return response

    @server.tool()
    def confirm_provider_change(confirmation_id: str) -> dict[str, object]:
        """Apply one prepared provider configuration change; confirmation IDs are single-use."""
        request = consume(confirmation_id, "provider_change")
        config = load_profile(request.profile)
        enabled = request.payload["enabled"] == "True"
        updated = (
            enable_provider(config, request.payload["provider_id"])
            if enabled
            else disable_provider(config, request.payload["provider_id"])
        )
        save_profile(updated)
        return {
            "profile": request.profile,
            "providers": list(updated.providers),
            "execution": "denied",
        }

    @server.tool()
    def prepare_profile_backup(profile: str, destination: str) -> dict[str, object]:
        """Prepare an encrypted local profile backup. Confirm once within five minutes."""
        target = Path(destination).expanduser().resolve()
        if target.exists():
            raise ValueError("backup destination already exists")
        response = prepare(profile, "profile_backup", {"destination": str(target)})
        response["destination"] = str(target)
        return response

    @server.tool()
    def confirm_profile_backup(confirmation_id: str) -> dict[str, object]:
        """Create one prepared encrypted backup; confirmation IDs are single-use."""
        request = consume(confirmation_id, "profile_backup")
        destination = export_backup(load_profile(request.profile), Path(request.payload["destination"]))
        return {"profile": request.profile, "backup": str(destination), "execution": "denied"}

    _validate_tool_registry(server)
    return server


def _validate_tool_registry(server: FastMCP) -> None:
    if set(server._tool_manager._tools) != _MCP_TOOL_ALLOWLIST:
        raise RuntimeError("MCP tool registry contains a prohibited capability")


def main() -> None:
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print("usage: stonks-mcp\n\nLocal MCP server for encrypted read-only portfolio data.")
        return
    create_server().run()
