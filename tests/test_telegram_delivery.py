from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from stonks_cli import telegram_delivery
from stonks_cli.config import ProfileConfig
from stonks_cli.storage import EncryptedLedger, generate_key_file
from stonks_cli.telegram_delivery import (
    TelegramArtifact,
    TelegramEventCategory,
    TelegramMessageField,
    add_recipient,
    configure,
    deliver,
    delivery_records,
    settings,
    settings_audit,
)


def _ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EncryptedLedger:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "profile.key"
    generate_key_file(key)
    return EncryptedLedger(ProfileConfig("personal", str(key)))


def test_telegram_default_is_disabled_and_content_is_minimized_and_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(telegram_delivery.platform, "system", lambda: "Linux")
    ledger = _ledger(tmp_path, monkeypatch)
    assert settings(ledger).enabled is False
    add_recipient(ledger, "primary", "token-secret", "recipient-secret", source="cli")
    configured = configure(
        ledger,
        enabled=True,
        recipient_aliases=("primary",),
        event_categories=(TelegramEventCategory.ADVISORY,),
        message_fields=(
            TelegramMessageField.INSTRUMENT,
            TelegramMessageField.ACTION,
            TelegramMessageField.RATIONALE,
        ),
        scheduled_enabled=True,
        source="cli",
    )
    sent = []
    monkeypatch.setattr(
        telegram_delivery,
        "notify_telegram",
        lambda token, chat_id, title, message: sent.append((token, chat_id, title, message)) or True,
    )
    artifact = TelegramArtifact(
        "advisory-1",
        TelegramEventCategory.ADVISORY,
        instrument="US:SPY",
        action="buy",
        rationale="trend confirmed",
        amounts="1000 USD",
        quantities="10 shares",
        balances="5000 USD",
    )

    records = deliver(ledger, artifact, scheduled=True, now=datetime(2026, 1, 1, tzinfo=UTC))

    assert configured.version == 3
    assert sent == [("token-secret", "recipient-secret", "stonks-cli", "US:SPY\nbuy\ntrend confirmed")]
    assert records[0].result == "delivered"
    assert records[0].profile == "personal"
    assert records[0].channel == "telegram"
    assert records[0].delivered_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert delivery_records(ledger) == records
    assert settings_audit(ledger)[-1].version == configured.version
    assert b"token-secret" not in ledger.path.read_bytes()
    assert b"recipient-secret" not in ledger.path.read_bytes()
    with ledger.connection() as connection:
        audit = connection.execute("SELECT * FROM telegram_delivery_audit").fetchone()
        assert "token" not in str(tuple(audit))
        assert "recipient" not in str(tuple(audit))


def test_telegram_macos_uses_keychain_not_encrypted_linux_credential_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(telegram_delivery.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(telegram_delivery.shutil, "which", lambda _: "/usr/bin/security")
    calls: list[tuple[str, ...]] = []

    class Result:
        returncode = 0
        stdout = ""

    def run(command, **_kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(telegram_delivery.subprocess, "run", run)
    ledger = _ledger(tmp_path, monkeypatch)

    add_recipient(ledger, "primary", "token-secret", "recipient-secret")

    assert [call[:3] for call in calls] == [
        ("security", "add-generic-password", "-U"),
        ("security", "add-generic-password", "-U"),
    ]
    with ledger.connection() as connection:
        assert connection.execute("SELECT * FROM telegram_credentials").fetchall() == []
