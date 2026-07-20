from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from stonks_cli.config import load_profile
from stonks_cli.ledger import import_csv, list_events
from stonks_cli.storage import EncryptedLedger


@dataclass(frozen=True)
class PendingImport:
    profile: str
    path: Path
    expires_at: datetime


def create_server() -> FastMCP:
    server = FastMCP("stonks-cli")
    pending: dict[str, PendingImport] = {}

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
        load_profile(profile)
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("CSV import path must be an existing regular file")
        confirmation_id = uuid4().hex
        expires_at = datetime.now(UTC) + timedelta(minutes=5)
        pending[confirmation_id] = PendingImport(profile, source, expires_at)
        return {
            "confirmation_id": confirmation_id,
            "profile": profile,
            "path": str(source),
            "expires_at": expires_at.isoformat(),
        }

    @server.tool()
    def confirm_csv_import(confirmation_id: str) -> dict[str, object]:
        """Execute one prepared CSV import. Confirmation IDs are single-use and expire after five minutes."""
        request = pending.pop(confirmation_id, None)
        if request is None or request.expires_at <= datetime.now(UTC):
            raise ValueError("CSV import confirmation is invalid or expired")
        config = load_profile(request.profile)
        inserted, skipped, source_hash = import_csv(EncryptedLedger(config), request.path)
        return {
            "profile": request.profile,
            "inserted": inserted,
            "skipped": skipped,
            "source_hash": source_hash,
            "execution": "denied",
        }

    return server


def main() -> None:
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print("usage: stonks-mcp\n\nLocal MCP server for encrypted read-only portfolio data.")
        return
    create_server().run()
