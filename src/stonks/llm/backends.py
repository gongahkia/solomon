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


class TransformersBackend:
    def __init__(self, model_path: str):
        self._model_path = (model_path or "").strip()

    def stream_chat(self, messages: list[ChatMessage]) -> Iterable[str]:
        if not self._model_path:
            raise ValueError("Transformers backend requires config.model.path")
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Transformers backend requires optional dependency. Install with: pip install transformers"
            ) from e

        # Minimal implementation: concatenate messages and generate a single response.
        prompt = "\n".join([f"{m.role}: {m.content}" for m in messages if m.content]) + "\nassistant:"
        tok = AutoTokenizer.from_pretrained(self._model_path)
        mdl = AutoModelForCausalLM.from_pretrained(self._model_path)
        inputs = tok(prompt, return_tensors="pt")
        out = mdl.generate(**inputs, max_new_tokens=256)
        txt = tok.decode(out[0], skip_special_tokens=True)
        # Best-effort: return only the tail after the last 'assistant:' marker.
        marker = "assistant:"
        if marker in txt:
            txt = txt.split(marker)[-1].strip()
        yield txt
