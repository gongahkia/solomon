import json

from typer.testing import CliRunner

from stonks_cli.cli import app
from stonks_cli.config import REDACTED_CONFIG_VALUE


def test_config_show_never_emits_top_level_or_nested_secret_values(tmp_path, monkeypatch):
    secrets = ("alpaca-api-secret", "webhook-secret", "bearer-secret", "session-secret")
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "api_keys": {"alpaca_api_key": secrets[0]},
                "webhook_url": f"https://example.test/hook?token={secrets[1]}",
                "strategy_params": {"headers": {"authorization": f"Bearer {secrets[2]}", "cookie": secrets[3]}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(path))

    result = CliRunner().invoke(app, ["show-config"])

    assert result.exit_code == 0
    assert all(secret not in result.output for secret in secrets)
    rendered = json.loads(result.output)
    assert rendered["api_keys"] == REDACTED_CONFIG_VALUE
    assert rendered["webhook_url"] == REDACTED_CONFIG_VALUE
    assert rendered["strategy_params"]["headers"] == {"authorization": REDACTED_CONFIG_VALUE, "cookie": REDACTED_CONFIG_VALUE}
