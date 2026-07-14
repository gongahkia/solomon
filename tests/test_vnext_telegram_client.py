import pytest

from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.telegram_client import send_telegram_message
from stonks_cli.vnext.telegram_configuration import TelegramDeliveryConfiguration


class _Response:
    status_code = 200

    def json(self):
        return {"ok": True, "result": {"message_id": 7}}


def test_telegram_client_posts_plain_text_to_documented_send_message_endpoint():
    calls = []

    receipt = send_telegram_message(
        TelegramDeliveryConfiguration("123456:ABC_def", "-100123"),
        "DAILY REPORT",
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or _Response(),
    )

    assert receipt.message_id == 7
    assert calls == [
        (("https://api.telegram.org/bot123456:ABC_def/sendMessage",), {"json_data": {"chat_id": "-100123", "text": "DAILY REPORT"}, "timeout": 5.0})
    ]


def test_telegram_client_fails_closed_for_invalid_text_or_malformed_response():
    configuration = TelegramDeliveryConfiguration("123456:ABC_def", "-100123")

    with pytest.raises(ValueError, match="1 through 4096"):
        send_telegram_message(configuration, "")
    with pytest.raises(VNextExternalDataError, match="response is malformed"):
        send_telegram_message(configuration, "DAILY REPORT", post=lambda *args, **kwargs: _MalformedResponse())


class _MalformedResponse:
    status_code = 200

    def json(self):
        return {"ok": False}
