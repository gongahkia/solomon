from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.request import Request, urlopen

from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.telegram_configuration import TelegramDeliveryConfiguration

_TELEGRAM_API_ROOT = "https://api.telegram.org"


@dataclass(frozen=True)
class _TelegramHTTPResponse:
    status_code: int
    data: object

    def json(self) -> object:
        return self.data


@dataclass(frozen=True)
class TelegramMessageReceipt:
    chat_id: str
    message_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.chat_id, str) or not self.chat_id:
            raise ValueError("Telegram receipt chat ID is invalid")
        if not isinstance(self.message_id, int) or isinstance(self.message_id, bool) or self.message_id < 1:
            raise ValueError("Telegram receipt message ID is invalid")


def _post_telegram_json(url: str, *, json_data: Mapping[str, str], timeout: float) -> _TelegramHTTPResponse:
    request = Request(
        url,
        data=json.dumps(dict(json_data)).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return _TelegramHTTPResponse(response.status, json.loads(response.read().decode("utf-8")))


def send_telegram_message(
    configuration: TelegramDeliveryConfiguration,
    text: str,
    *,
    timeout_seconds: float = 5.0,
    post: Callable[..., object] | None = None,
) -> TelegramMessageReceipt:
    if not isinstance(configuration, TelegramDeliveryConfiguration):
        raise TypeError("Telegram client requires delivery configuration")
    if not isinstance(text, str) or not 1 <= len(text) <= 4096:
        raise ValueError("Telegram message text must contain 1 through 4096 characters")
    if not isinstance(timeout_seconds, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Telegram client timeout is invalid")
    transport = _post_telegram_json if post is None else post
    if not callable(transport):
        raise TypeError("Telegram client post transport is invalid")
    try:
        response = transport(
            f"{_TELEGRAM_API_ROOT}/bot{configuration.bot_token}/sendMessage",
            json_data={"chat_id": configuration.chat_id, "text": text},
            timeout=timeout_seconds,
        )
        status_code = getattr(response, "status_code", None)
        decoder = getattr(response, "json", None)
        if not isinstance(status_code, int) or not 200 <= status_code < 300 or not callable(decoder):
            raise ValueError("response is unavailable")
        data = decoder()
    except Exception as error:
        raise VNextExternalDataError("Telegram message delivery is unavailable") from error
    if not isinstance(data, Mapping) or data.get("ok") is not True or not isinstance(data.get("result"), Mapping):
        raise VNextExternalDataError("Telegram message delivery response is malformed")
    message_id = data["result"].get("message_id")
    if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id < 1:
        raise VNextExternalDataError("Telegram message delivery response is malformed")
    return TelegramMessageReceipt(configuration.chat_id, message_id)
