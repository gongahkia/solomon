from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import stonks_cli.cli as cli
from stonks_cli.cli import app
from stonks_cli.config import AppConfig
from stonks_cli.errors import ExitCodes
from stonks_cli.vnext.account_import import import_moomoo_accounts
from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.moomoo import MoomooAccount, MoomooSdkCompatibility, MoomooSdkStatus


def test_broker_account_import_cli_emits_read_only_accounts(monkeypatch):
    monkeypatch.setattr(cli, "import_moomoo_accounts", lambda config: (MoomooAccount("100", 0, "REAL"),))

    result = CliRunner().invoke(app, ["import-account"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "accounts": [{"account_id": "100", "account_index": 0, "trading_environment": "REAL"}],
        "broker": "moomoo",
        "endpoint": "127.0.0.1:11111",
        "read_only": True,
    }


def test_broker_account_import_cli_fails_closed_for_external_data(monkeypatch):
    def fail(config: AppConfig) -> tuple[MoomooAccount, ...]:
        raise VNextExternalDataError("Moomoo account list is malformed")

    monkeypatch.setattr(cli, "import_moomoo_accounts", fail)

    result = CliRunner().invoke(app, ["import-account"])

    assert result.exit_code == ExitCodes.PROVIDER_ERROR
    assert "Moomoo account list is malformed" in result.output


def test_broker_account_import_cli_requires_explicit_broker_configuration():
    result = CliRunner().invoke(app, ["import-account"])

    assert result.exit_code == ExitCodes.BAD_CONFIG
    assert "account import is not enabled" in result.output


def test_import_moomoo_accounts_reads_normalized_accounts_and_rejects_empty_external_data():
    config = AppConfig.model_validate(
        {"vnext": {"enabled": True, "moomoo": {"enabled": True}, "features": {"broker_data": True}}}
    )

    def compatible() -> MoomooSdkCompatibility:
        return MoomooSdkCompatibility(MoomooSdkStatus.COMPATIBLE, "sdk_compatible", "9.1.0")

    class Context:
        def __init__(self, records):
            self.records = records

        def get_acc_list(self):
            return 0, self.records

        def close(self) -> None:
            return None

    assert import_moomoo_accounts(
        config,
        sdk_compatibility=compatible,
        context_factory=lambda host, port: Context([{"acc_id": "100", "acc_index": 0, "trd_env": "REAL"}]),
    ) == (MoomooAccount("100", 0, "REAL"),)
    with pytest.raises(VNextExternalDataError, match="account list is empty"):
        import_moomoo_accounts(
            config,
            sdk_compatibility=compatible,
            context_factory=lambda host, port: Context([]),
        )
