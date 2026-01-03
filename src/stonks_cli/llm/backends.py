from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import platform
import sys
from pathlib import Path
from typing import Iterable, Protocol


def build_chat_backend() -> tuple["ChatBackend", str, str | None, str | None]:
    """Build the configured chat backend.

    Returns (backend, selected_backend_name, selected_model_or_path, warning_message).
    Warning is non-None when we fall back.
    """

    from stonks_cli.config import load_config

    cfg = load_config().model
    return _build_from_model_cfg(cfg)


def build_chat_backend_from_overrides(
    *,
    backend: str | None = None,
    model: str | None = None,
    host: str | None = None,
    path: str | None = None,
    offline: bool | None = None,
    max_new_tokens: int | None = None,
    temperature: float | None = None,
) -> tuple["ChatBackend", str, str | None, str | None]:
    """Build a backend using config + provided overrides (non-persistent)."""

    from stonks_cli.config import load_config

    cfg = load_config().model
    updates: dict[str, object] = {}
    if backend is not None:
        updates["backend"] = backend
    if model is not None:
        updates["model"] = model
    if host is not None:
        updates["host"] = host
    if path is not None:
        updates["path"] = path
    if offline is not None:
        updates["offline"] = offline
    if max_new_tokens is not None:
        updates["max_new_tokens"] = max_new_tokens
    if temperature is not None:
        updates["temperature"] = temperature

    if updates:
        cfg = cfg.model_copy(update=updates)

    return _build_from_model_cfg(cfg)


def _build_from_model_cfg(cfg) -> tuple["ChatBackend", str, str | None, str | None]:
    requested = (getattr(cfg, "backend", None) or "auto").lower()

    selected = _select_backend(
        requested,
        offline=bool(getattr(cfg, "offline", False)),
        model=str(getattr(cfg, "model", "") or ""),
        path=(getattr(cfg, "path", None) or None),
    )
    if selected == "transformers":
        try:
            path = _coerce_model_ref("transformers", cfg)
            return (
                TransformersBackend(
                    model_path=path,
                    offline=cfg.offline,
                    max_new_tokens=cfg.max_new_tokens,
                    temperature=cfg.temperature,
                ),
                "transformers",
                path,
                None,
            )
        except Exception as e:
            fb = "llama_cpp" if _has_module("llama_cpp") else "ollama"
            warn = f"transformers unavailable: {e}; falling back to {fb}"
            return build_chat_backend_with_override(fb, warning=warn)

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
                path,
                None,
            )
        except Exception as e:
            fb = "ollama" if not cfg.offline else "transformers"
            warn = f"llama_cpp unavailable: {e}; falling back to {fb}"
            return build_chat_backend_with_override(fb, warning=warn)

    if selected == "mlx":
        try:
            path = _coerce_model_ref("mlx", cfg)
            return (
                MLXBackend(
                    model_path=path,
                    offline=cfg.offline,
                    max_new_tokens=cfg.max_new_tokens,
                    temperature=cfg.temperature,
                ),
                "mlx",
                path,
                None,
            )
        except Exception as e:
            fb = "llama_cpp" if _has_module("llama_cpp") else "ollama"
            warn = f"mlx unavailable: {e}; falling back to {fb}"
            return build_chat_backend_with_override(fb, warning=warn)

    if selected == "onnx":
        try:
            path = cfg.path or cfg.model
            return (OnnxBackend(model_path=path), "onnx", path, None)
        except Exception as e:
            warn = f"onnx unavailable: {e}; falling back to ollama"
            return build_chat_backend_with_override("ollama", warning=warn)

    # Default: ollama.
    return (OllamaBackend(host=cfg.host, model=cfg.model), "ollama", cfg.model, None)


def build_chat_backend_with_override(
    backend: str, *, warning: str | None = None
) -> tuple["ChatBackend", str, str | None, str | None]:
    """Build a backend by explicit name, used for fallbacks."""

    from stonks_cli.config import load_config

    cfg = load_config().model
    b = (backend or "auto").lower()
    if b == "transformers":
        path = _coerce_model_ref("transformers", cfg)
        return (
            TransformersBackend(
                model_path=path,
                offline=cfg.offline,
                max_new_tokens=cfg.max_new_tokens,
                temperature=cfg.temperature,
            ),
            "transformers",
            path,
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
            cfg.path,
            warning,
        )
    if b == "mlx":
        path = _coerce_model_ref("mlx", cfg)
        return (
            MLXBackend(
                model_path=path,
                offline=cfg.offline,
                max_new_tokens=cfg.max_new_tokens,
                temperature=cfg.temperature,
            ),
            "mlx",
            path,
            warning,
        )
    if b == "onnx":
        path = cfg.path or cfg.model
        return (OnnxBackend(model_path=path), "onnx", path, warning)
    return (OllamaBackend(host=cfg.host, model=cfg.model), "ollama", cfg.model, warning)


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _is_macos_arm64() -> bool:
    return sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}


def _looks_like_hf_repo_id(value: str) -> bool:
    v = (value or "").strip()
    # Minimal heuristic: org/repo
    return "/" in v and " " not in v and not v.startswith("/") and not v.endswith("/")


def _is_existing_path(value: str | None) -> bool:
    if not value:
        return False
    try:
        return Path(value).expanduser().exists()
    except Exception:
        return False


def _is_existing_dir(value: str | None) -> bool:
    if not value:
        return False
    try:
        return Path(value).expanduser().is_dir()
    except Exception:
        return False


def _is_existing_file(value: str | None) -> bool:
    if not value:
        return False
    try:
        return Path(value).expanduser().is_file()
    except Exception:
        return False


def _select_backend(requested: str, *, offline: bool, model: str, path: str | None) -> str:
    requested = (requested or "auto").lower()
    if requested not in {"auto", "ollama", "llama_cpp", "mlx", "transformers", "onnx"}:
        requested = "auto"

    if requested != "auto":
        return requested

    # Auto defaults by platform + installed deps, but also require that config is usable.
    # - For MLX/Transformers: allow HF repo id OR local path; offline requires local path.
    # - For llama.cpp: requires local GGUF path.

    can_use_mlx = _has_module("mlx_lm") and (_looks_like_hf_repo_id(model) or _is_existing_dir(path))
    can_use_transformers = _has_module("transformers") and (
        _looks_like_hf_repo_id(model) or _is_existing_dir(path)
    )
    can_use_llama_cpp = _has_module("llama_cpp") and _is_existing_file(path)

    if offline:
        # Offline forbids Ollama + remote downloads.
        if can_use_mlx and _is_existing_dir(path):
            return "mlx"
        if can_use_llama_cpp:
            return "llama_cpp"
        if can_use_transformers and _is_existing_dir(path):
            return "transformers"
        # If nothing is configured, choose a local backend that can at least emit a helpful config error.
        return "llama_cpp" if _has_module("llama_cpp") else "transformers"

    # Online / service allowed.
    if _is_macos_arm64() and can_use_mlx:
        return "mlx"
    if can_use_llama_cpp:
        return "llama_cpp"
    if can_use_transformers:
        return "transformers"
    return "ollama"


def supported_backends() -> list[str]:
    """Return backend keys that this build understands (not necessarily installed)."""

    return ["auto", "ollama", "llama_cpp", "mlx", "transformers", "onnx"]


def select_backend(
    requested: str | None,
    *,
    offline: bool,
    model: str = "",
    path: str | None = None,
) -> str:
    """Select a backend key using the same rules as `build_chat_backend()`."""

    return _select_backend((requested or "auto"), offline=offline, model=model, path=path)


def _coerce_model_ref(backend: str, cfg) -> str:
    """Return a model ref for backends that accept either a local path or HF repo id.

    We keep config.model (default "gemma3") for Ollama, but MLX/Transformers need either:
    - cfg.path (recommended for offline)
    - cfg.model as HF repo id (org/repo)
    If neither is usable, pick a sensible public default.
    """

    if getattr(cfg, "path", None):
        return str(cfg.path)

    m = str(getattr(cfg, "model", "") or "").strip()
    if _looks_like_hf_repo_id(m):
        return m

    if backend == "mlx":
        return "mlx-community/Llama-3.2-3B-Instruct-4bit"
    if backend == "transformers":
        return "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
    return m


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
                "Ollama backend requires optional dependency. Install with: pip install -e '.[ollama]'"
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

        # For Transformers, a local reference must be a directory (not a file).
        if self._model_path and (not _looks_like_hf_repo_id(self._model_path)) and (not _is_existing_dir(self._model_path)):
            raise ValueError(
                "Transformers backend requires config.model.path to be a local model directory, "
                "or config.model.model as a HuggingFace repo id (org/repo)"
            )

    def _ensure_loaded(self):
        if self._tok is not None and self._mdl is not None:
            return
        if not self._model_path:
            raise ValueError("Transformers backend requires config.model.path or config.model.model as a HuggingFace repo id (org/repo)")
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Transformers backend requires optional dependency. Install with: pip install -e '.[transformers]'"
            ) from e

        kwargs = {}
        if self._offline:
            from pathlib import Path

            p = Path(self._model_path).expanduser()
            if not p.is_dir():
                raise FileNotFoundError(f"offline=true requires a local model directory, not: {self._model_path}")
            kwargs["local_files_only"] = True
        else:
            # Avoid surprising Hugging Face auth errors on non-repo ids like "gemma3".
            if not _looks_like_hf_repo_id(self._model_path) and not _is_existing_dir(self._model_path):
                raise ValueError(
                    "Transformers backend requires either a local model directory (model.path) "
                    "or a HuggingFace repo id like 'TinyLlama/TinyLlama-1.1B-Chat-v1.0' (model.model)."
                )

        self._tok = AutoTokenizer.from_pretrained(self._model_path, **kwargs)
        self._mdl = AutoModelForCausalLM.from_pretrained(self._model_path, **kwargs)
        try:
            self._mdl.eval()
        except Exception:
            pass

    def stream_chat(self, messages: list[ChatMessage]) -> Iterable[str]:
        self._ensure_loaded()
        assert self._tok is not None
        assert self._mdl is not None

        # Minimal implementation: concatenate messages and generate a single response.
        prompt = _format_messages_as_prompt(messages)
        inputs = self._tok(prompt, return_tensors="pt")
        try:
            import torch  # type: ignore

            ctx = torch.no_grad()
        except Exception:  # pragma: no cover
            ctx = None

        if ctx is None:
            out = self._mdl.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                do_sample=self._temperature > 0,
                temperature=self._temperature,
            )
        else:
            with ctx:
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
        # Reduce extremely verbose Metal/back-end logs in interactive usage.
        self._llm = Llama(model_path=str(p), verbose=False)

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

        # For MLX, a local reference must be a directory (not a file).
        if self._model_path and (not _looks_like_hf_repo_id(self._model_path)) and (not _is_existing_dir(self._model_path)):
            raise ValueError(
                "MLX backend requires config.model.path to be a local model directory, "
                "or config.model.model as a HuggingFace repo id (org/repo)"
            )

    def _ensure_loaded(self):
        if self._tok is not None and self._mdl is not None:
            return
        if not self._model_path:
            raise ValueError("MLX backend requires config.model.path or config.model.model as a HuggingFace repo id (org/repo)")
        if self._offline:
            # Enforce local path usage for offline mode (avoid implicit HuggingFace downloads).
            from pathlib import Path

            p = Path(self._model_path).expanduser()
            if not p.is_dir():
                raise FileNotFoundError(f"offline=true requires a local model directory, not: {self._model_path}")
        else:
            # Avoid surprising Hugging Face auth errors on non-repo ids like "gemma3".
            if not _looks_like_hf_repo_id(self._model_path) and not _is_existing_dir(self._model_path):
                raise ValueError(
                    "MLX backend requires either a local model directory (model.path) "
                    "or a HuggingFace repo id like 'mlx-community/Llama-3.2-3B-Instruct-4bit' (model.model)."
                )
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
        # Best-effort: mlx-lm APIs vary by version.
        # Newer versions (e.g. 0.29.x) expect a `sampler=` callable instead of `temp=`.
        kwargs: dict[str, object] = {"max_tokens": self._max_new_tokens}
        try:
            from mlx_lm.sample_utils import make_sampler  # type: ignore

            kwargs["sampler"] = make_sampler(temp=float(self._temperature))
        except Exception:
            # Older versions accepted temp directly.
            kwargs["temp"] = float(self._temperature)

        try:
            txt = generate(self._mdl, self._tok, prompt=prompt, **kwargs)
        except TypeError:
            # Fallback across API differences.
            kwargs.pop("sampler", None)
            kwargs["temp"] = float(self._temperature)
            txt = generate(self._mdl, self._tok, prompt=prompt, **kwargs)
        # Some versions return just text, others return a dict.
        if isinstance(txt, dict):
            txt = txt.get("text") or ""
        yield str(txt).strip()


def _format_messages_as_prompt(messages: list[ChatMessage]) -> str:
    # Backend-agnostic prompt for local models that don't support a native chat template.
    # Keep it short and structured to reduce prompt echo.
    max_messages = 30
    trimmed = [m for m in messages if (m.content or "").strip()]
    if len(trimmed) > max_messages:
        trimmed = trimmed[-max_messages:]

    out: list[str] = []
    for m in trimmed:
        role = (m.role or "").strip().lower()
        if role == "system":
            out.append(f"### System\n{m.content.strip()}\n")
        elif role == "user":
            out.append(f"### User\n{m.content.strip()}\n")
        else:
            out.append(f"### Assistant\n{m.content.strip()}\n")

    out.append(
        "### Assistant\n"
        "Respond with the assistant answer only. Do not repeat the prompt or any '###' blocks.\n"
    )
    return "\n".join(out)


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
