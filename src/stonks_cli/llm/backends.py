from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import platform
import sys
from typing import Iterable, Protocol


def build_chat_backend():
    """Build the configured chat backend.

    Returns (backend, selected_backend_name, warning_message).
    Warning is non-None when we fall back.
    """

    from stonks_cli.config import load_config

    cfg = load_config().model
    requested = (cfg.backend or "auto").lower()

    selected = _select_backend(requested, offline=bool(getattr(cfg, "offline", False)))
    if selected == "transformers":
        try:
            path = cfg.path or cfg.model
            return (
                TransformersBackend(
                    model_path=path,
                    offline=cfg.offline,
                    max_new_tokens=cfg.max_new_tokens,
                    temperature=cfg.temperature,
                ),
                "transformers",
                None,
            )
        except Exception as e:
            fb = "llama_cpp" if _has_module("llama_cpp") else "ollama"
            warn = f"transformers unavailable: {e}; falling back to {fb}"
            return build_chat_backend_with_override(fb)

    if selected == "llama_cpp":
        try:
            path = cfg.path
            return (
                LlamaCppBackend(
                    model_path=path,
                    max_new_tokens=cfg.max_new_tokens,
                    temperature=cfg.temperature,
                ),
                "llama_cpp",
                None,
            )
        except Exception as e:
            fb = "ollama" if not cfg.offline else "transformers"
            warn = f"llama_cpp unavailable: {e}; falling back to {fb}"
            return build_chat_backend_with_override(fb, warning=warn)

    if selected == "mlx":
        try:
            path = cfg.path or cfg.model
            return (
                MLXBackend(
                    model_path=path,
                    offline=cfg.offline,
                    max_new_tokens=cfg.max_new_tokens,
                    temperature=cfg.temperature,
                ),
                "mlx",
                None,
            )
        except Exception as e:
            fb = "llama_cpp" if _has_module("llama_cpp") else "ollama"
            warn = f"mlx unavailable: {e}; falling back to {fb}"
            return build_chat_backend_with_override(fb, warning=warn)

    if selected == "onnx":
        try:
            path = cfg.path or cfg.model
            return (OnnxBackend(model_path=path), "onnx", None)
        except Exception as e:
            warn = f"onnx unavailable: {e}; falling back to ollama"
            return build_chat_backend_with_override("ollama", warning=warn)

    # Default: ollama.
    return (OllamaBackend(host=cfg.host, model=cfg.model), "ollama", None)


def build_chat_backend_with_override(backend: str, *, warning: str | None = None):
    """Build a backend by explicit name, used for fallbacks."""

    from stonks_cli.config import load_config

    cfg = load_config().model
    b = (backend or "auto").lower()
    if b == "transformers":
        path = cfg.path or cfg.model
        return (
            TransformersBackend(
                model_path=path,
                offline=cfg.offline,
                max_new_tokens=cfg.max_new_tokens,
                temperature=cfg.temperature,
            ),
            "transformers",
            warning,
        )
    if b == "llama_cpp":
        return (
            LlamaCppBackend(
                model_path=cfg.path,
                max_new_tokens=cfg.max_new_tokens,
                temperature=cfg.temperature,
            ),
            "llama_cpp",
            warning,
        )
    if b == "mlx":
        path = cfg.path or cfg.model
        return (
            MLXBackend(
                model_path=path,
                offline=cfg.offline,
                max_new_tokens=cfg.max_new_tokens,
                temperature=cfg.temperature,
            ),
            "mlx",
            warning,
        )
    if b == "onnx":
        path = cfg.path or cfg.model
        return (OnnxBackend(model_path=path), "onnx", warning)
    return (OllamaBackend(host=cfg.host, model=cfg.model), "ollama", warning)


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _is_macos_arm64() -> bool:
    return sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}


def _select_backend(requested: str, *, offline: bool) -> str:
    requested = (requested or "auto").lower()
    if requested not in {"auto", "ollama", "llama_cpp", "mlx", "transformers", "onnx"}:
        requested = "auto"

    if requested != "auto":
        return requested

    # Auto defaults by platform; only choose ollama when offline is False.
    if _is_macos_arm64() and _has_module("mlx_lm"):
        return "mlx"
    if _has_module("llama_cpp"):
        return "llama_cpp"
    if _has_module("transformers"):
        return "transformers"
    if offline:
        # Nothing usable is installed, but offline forbids remote/daemon approaches.
        return "transformers"
    return "ollama"


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
    def __init__(
        self,
        model_path: str,
        *,
        offline: bool = False,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
    ):
        self._model_path = (model_path or "").strip()
        self._offline = bool(offline)
        self._max_new_tokens = int(max_new_tokens)
        self._temperature = float(temperature)

        self._tok = None
        self._mdl = None

    def _ensure_loaded(self):
        if self._tok is not None and self._mdl is not None:
            return
        if not self._model_path:
            raise ValueError("Transformers backend requires config.model.path")
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Transformers backend requires optional dependency. Install with: pip install -e '.[transformers]'"
            ) from e

        kwargs = {}
        if self._offline:
            kwargs["local_files_only"] = True

        self._tok = AutoTokenizer.from_pretrained(self._model_path, **kwargs)
        self._mdl = AutoModelForCausalLM.from_pretrained(self._model_path, **kwargs)

    def stream_chat(self, messages: list[ChatMessage]) -> Iterable[str]:
        self._ensure_loaded()
        assert self._tok is not None
        assert self._mdl is not None

        # Minimal implementation: concatenate messages and generate a single response.
        prompt = _format_messages_as_prompt(messages)
        inputs = self._tok(prompt, return_tensors="pt")
        out = self._mdl.generate(
            **inputs,
            max_new_tokens=self._max_new_tokens,
            do_sample=self._temperature > 0,
            temperature=self._temperature,
        )
        txt = self._tok.decode(out[0], skip_special_tokens=True)
        # Best-effort: return only the tail after the last 'assistant:' marker.
        marker = "assistant:"
        if marker in txt:
            txt = txt.split(marker)[-1].strip()
        yield txt


class LlamaCppBackend:
    def __init__(
        self,
        model_path: str | None,
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
    ):
        self._model_path = (model_path or "").strip()
        self._max_new_tokens = int(max_new_tokens)
        self._temperature = float(temperature)
        self._llm = None

    def _ensure_loaded(self):
        if self._llm is not None:
            return
        if not self._model_path:
            raise ValueError("llama.cpp backend requires config.model.path (GGUF file path)")
        from pathlib import Path

        p = Path(self._model_path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"GGUF model file not found: {p}")
        try:
            from llama_cpp import Llama  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "llama.cpp backend requires optional dependency. Install with: pip install -e '.[llama-cpp]'"
            ) from e
        self._llm = Llama(model_path=str(p))

    def stream_chat(self, messages: list[ChatMessage]) -> Iterable[str]:
        self._ensure_loaded()
        assert self._llm is not None

        # llama-cpp-python supports OpenAI-like chat completions for many GGUF chat models.
        stream = self._llm.create_chat_completion(
            messages=[{"role": m.role, "content": m.content} for m in messages if (m.content or "").strip()],
            temperature=self._temperature,
            max_tokens=self._max_new_tokens,
            stream=True,
        )
        for chunk in stream:
            try:
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
            except Exception:
                continue


class MLXBackend:
    def __init__(
        self,
        model_path: str,
        *,
        offline: bool = False,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
    ):
        self._model_path = (model_path or "").strip()
        self._offline = bool(offline)
        self._max_new_tokens = int(max_new_tokens)
        self._temperature = float(temperature)

        self._tok = None
        self._mdl = None

    def _ensure_loaded(self):
        if self._tok is not None and self._mdl is not None:
            return
        if not self._model_path:
            raise ValueError("MLX backend requires config.model.path")
        if self._offline:
            # Enforce local path usage for offline mode (avoid implicit HuggingFace downloads).
            from pathlib import Path

            p = Path(self._model_path).expanduser()
            if not p.exists():
                raise FileNotFoundError(f"offline=true requires a local model directory, not: {self._model_path}")
        try:
            from mlx_lm import load  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("MLX backend requires optional dependency. Install with: pip install -e '.[mlx]'") from e

        # MLX supports local directories and (optionally) HF ids; offline enforcement handled later.
        self._mdl, self._tok = load(self._model_path)

    def stream_chat(self, messages: list[ChatMessage]) -> Iterable[str]:
        self._ensure_loaded()
        assert self._tok is not None
        assert self._mdl is not None

        try:
            from mlx_lm import generate  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("MLX backend requires optional dependency. Install with: pip install -e '.[mlx]'") from e

        prompt = _format_messages_as_prompt(messages)
        # Best-effort: mlx-lm APIs vary by version; return a single response chunk.
        txt = generate(
            self._mdl,
            self._tok,
            prompt=prompt,
            max_tokens=self._max_new_tokens,
            temp=self._temperature,
        )
        # Some versions return just text, others return a dict.
        if isinstance(txt, dict):
            txt = txt.get("text") or ""
        yield str(txt).strip()


def _format_messages_as_prompt(messages: list[ChatMessage]) -> str:
    # Minimal, backend-agnostic prompt; backends with native chat templates can override.
    lines = [f"{m.role}: {m.content}" for m in messages if (m.content or "").strip()]
    return "\n".join(lines) + "\nassistant:"


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
