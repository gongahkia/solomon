from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class ChatBackend(Protocol):
    def stream_chat(self, messages: list[ChatMessage]) -> Iterable[str]:
        ...


class OllamaBackend:
    def __init__(self, host: str, model: str):
        self._host = host
        self._model = model

    def stream_chat(self, messages: list[ChatMessage]) -> Iterable[str]:
        try:
            from ollama import Client
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Ollama backend requires optional dependency. Install with: pip install 'stonks[ollama]'"
            ) from e

        client = Client(host=self._host)
        stream = client.chat(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            stream=True,
        )
        for chunk in stream:
            msg = chunk.get("message") or {}
            content = msg.get("content")
            if content:
                yield content
