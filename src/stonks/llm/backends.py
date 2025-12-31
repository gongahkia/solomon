from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


def build_chat_backend():
    """Build the configured chat backend.

    Returns (backend, warning_message). Warning is non-None when we fall back.
    """

    from stonks.config import load_config

    cfg = load_config().model
    requested = (cfg.backend or "ollama").lower()

    if requested == "transformers":
        try:
            path = cfg.path or cfg.model
            return TransformersBackend(model_path=path), None
        except Exception as e:
            return OllamaBackend(host=cfg.host, model=cfg.model), f"transformers unavailable: {e}; falling back to ollama"

    if requested == "onnx":
        try:
            path = cfg.path or cfg.model
            return OnnxBackend(model_path=path), None
        except Exception as e:
            return OllamaBackend(host=cfg.host, model=cfg.model), f"onnx unavailable: {e}; falling back to ollama"

    return OllamaBackend(host=cfg.host, model=cfg.model), None


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


class OnnxBackend:
    def __init__(self, model_path: str):
        self._model_path = (model_path or "").strip()

    def stream_chat(self, messages: list[ChatMessage]) -> Iterable[str]:
        if not self._model_path:
            raise ValueError("ONNX backend requires config.model.path")
        try:
            import onnxruntime  # type: ignore  # noqa: F401
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "ONNX backend requires optional dependency. Install with: pip install onnxruntime"
            ) from e

        # Stub: real ONNX text generation requires model-specific tokenization and decoding.
        prompt = "\n".join([f"{m.role}: {m.content}" for m in messages if m.content])
        raise NotImplementedError(
            "ONNX backend wiring is present, but inference is model-specific. "
            "Provide an ONNX text-generation pipeline or use the Ollama backend. "
            f"(prompt preview: {prompt[:120]!r})"
        )
