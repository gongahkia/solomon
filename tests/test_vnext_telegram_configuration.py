import pytest

from stonks_cli.config import AppConfig
from stonks_cli.vnext.errors import VNextConfigurationError
from stonks_cli.vnext.telegram_configuration import validate_telegram_configuration


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "vnext": {
                "enabled": True,
                "features": {"operator_reports": True},
                "operator": {"telegram": {"enabled": True, "bot_token_env": "TELEGRAM_TOKEN", "chat_id_env": "TELEGRAM_CHAT"}},
            }
        }
    )


def test_telegram_configuration_resolves_enabled_environment_secrets_without_repr_leakage():
    configuration = validate_telegram_configuration(_config(), {"TELEGRAM_TOKEN": "123456:ABC_def", "TELEGRAM_CHAT": "-100123"})

    assert configuration.chat_id == "-100123"
    assert "123456:ABC_def" not in repr(configuration)


def test_telegram_configuration_fails_closed_for_disabled_missing_or_malformed_values():
    with pytest.raises(VNextConfigurationError, match="not enabled"):
        validate_telegram_configuration(AppConfig(), {})
    with pytest.raises(VNextConfigurationError, match="missing"):
        validate_telegram_configuration(_config(), {"TELEGRAM_TOKEN": "123456:ABC_def"})
    with pytest.raises(VNextConfigurationError, match="invalid"):
        validate_telegram_configuration(_config(), {"TELEGRAM_TOKEN": "bad token", "TELEGRAM_CHAT": "-100123"})
