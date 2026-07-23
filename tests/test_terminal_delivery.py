from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from stonks_cli.config import ProfileConfig
from stonks_cli.storage import EncryptedLedger, generate_key_file
from stonks_cli.terminal_delivery import (
    create_artifact,
    latest_scheduled_artifact,
    persist_scheduled_artifact,
    render_terminal,
)


def test_terminal_delivery_persists_scheduled_artifact_encrypted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    artifact = create_artifact(
        "report", '{"report":"private"}', created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    stored = persist_scheduled_artifact(ledger, "com.stonks-cli.personal", artifact, "succeeded")

    assert stored.profile == "personal"
    assert render_terminal(artifact) == '{"report":"private"}'
    assert latest_scheduled_artifact(ledger, "com.stonks-cli.personal") == stored
    assert b"private" not in ledger.path.read_bytes()
