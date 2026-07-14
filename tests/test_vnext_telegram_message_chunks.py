import pytest

from stonks_cli.vnext.telegram_message_chunks import TELEGRAM_MAX_MESSAGE_CHARACTERS, chunk_telegram_message


def test_telegram_message_chunking_preserves_exact_content_and_prefers_newline_boundaries():
    text = "a" * 10 + "\n" + "b" * 10

    chunks = chunk_telegram_message(text, 12)

    assert chunks == ("a" * 10 + "\n", "b" * 10)
    assert "".join(chunks) == text
    assert all(len(chunk) <= 12 for chunk in chunks)


def test_telegram_message_chunking_fails_closed_for_invalid_text_or_limits():
    with pytest.raises(ValueError, match="text is invalid"):
        chunk_telegram_message("")
    with pytest.raises(ValueError, match="maximum length"):
        chunk_telegram_message("text", TELEGRAM_MAX_MESSAGE_CHARACTERS + 1)
