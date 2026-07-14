from __future__ import annotations

TELEGRAM_MAX_MESSAGE_CHARACTERS = 4096


def chunk_telegram_message(text: str, maximum_characters: int = TELEGRAM_MAX_MESSAGE_CHARACTERS) -> tuple[str, ...]:
    if not isinstance(text, str) or not text:
        raise ValueError("Telegram message text is invalid")
    if not isinstance(maximum_characters, int) or isinstance(maximum_characters, bool) or not 1 <= maximum_characters <= TELEGRAM_MAX_MESSAGE_CHARACTERS:
        raise ValueError("Telegram message maximum length is invalid")
    chunks: list[str] = []
    remaining = text
    while len(remaining) > maximum_characters:
        newline_index = remaining.rfind("\n", 0, maximum_characters + 1)
        split_at = newline_index + 1 if newline_index > 0 else maximum_characters
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    chunks.append(remaining)
    return tuple(chunks)
