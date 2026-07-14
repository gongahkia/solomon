from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from stonks_cli.config import AppConfig
from stonks_cli.vnext.errors import VNextConfigurationError

_ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
_BOT_TOKEN_PATTERN = re.compile(r"[0-9]+:[A-Za-z0-9_-]+\Z")


@dataclass(frozen=True)
class TelegramDeliveryConfiguration:
    bot_token: str = field(repr=False)
    chat_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.bot_token, str) or not _BOT_TOKEN_PATTERN.fullmatch(self.bot_token):
            raise ValueError("Telegram bot token is invalid")
        if not isinstance(self.chat_id, str) or not self.chat_id:
            raise ValueError("Telegram chat ID is invalid")


def validate_telegram_configuration(
    config: AppConfig, environment: Mapping[str, str] | None = None
) -> TelegramDeliveryConfiguration:
    if not isinstance(config, AppConfig):
        raise TypeError("Telegram configuration requires app configuration")
    if not config.vnext.enabled or not config.vnext.features.operator_reports or not config.vnext.operator.telegram.enabled:
        raise VNextConfigurationError("vNext Telegram operator reports are not enabled")
    source = os.environ if environment is None else environment
    if not isinstance(source, Mapping):
        raise TypeError("Telegram configuration environment is invalid")
    token_env = config.vnext.operator.telegram.bot_token_env
    chat_id_env = config.vnext.operator.telegram.chat_id_env
    if not all(isinstance(name, str) and _ENVIRONMENT_VARIABLE_PATTERN.fullmatch(name) for name in (token_env, chat_id_env)):
        raise VNextConfigurationError("Telegram secret environment variable is invalid")
    token = source.get(token_env)
    chat_id = source.get(chat_id_env)
    if not isinstance(token, str) or not token.strip() or not isinstance(chat_id, str) or not chat_id.strip():
        raise VNextConfigurationError("Telegram secret environment variable is missing")
    try:
        return TelegramDeliveryConfiguration(token.strip(), chat_id.strip())
    except ValueError as error:
        raise VNextConfigurationError("Telegram configuration is invalid") from error
