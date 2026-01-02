#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _ensure_macos() -> None:
    if sys.platform != "darwin":
        raise SystemExit("This smoke test is intended for macOS only.")


def _project_root() -> Path:
    # scripts/ -> project root
    return Path(__file__).resolve().parents[1]


def _setup_local_hf_cache(root: Path) -> Path:
    cache_root = root / ".cache" / "stonks-cli" / "llm-smoke"
    cache_root.mkdir(parents=True, exist_ok=True)

    # Keep downloads local to the repo so cleanup is easy.
    os.environ.setdefault("HF_HOME", str(cache_root / "hf-home"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(Path(os.environ["HF_HOME"]) / "hub"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(Path(os.environ["HF_HOME"]) / "hub"))

    return cache_root


def _print_ok(name: str, extra: str = "") -> None:
    msg = f"ok {name}"
    if extra:
        msg += f" {extra}"
    print(msg)


def _print_err(name: str, err: BaseException) -> None:
    print(f"error {name}: {err}")


def _test_transformers(model_id: str) -> None:
    from stonks_cli.llm.backends import ChatMessage, TransformersBackend

    backend = TransformersBackend(model_id, offline=False, max_new_tokens=32, temperature=0.0)
    chunks = list(
        backend.stream_chat(
            [
                ChatMessage(role="system", content="You are a helpful assistant."),
                ChatMessage(role="user", content="Say 'hello' and stop."),
            ]
        )
    )
    out = "".join(chunks).strip()
    if not out:
        raise RuntimeError("empty output")


def _pick_first_existing_hf_model(candidates: list[str]) -> str:
    try:
        from huggingface_hub import HfApi

        api = HfApi()
        for repo_id in candidates:
            try:
                api.model_info(repo_id)
                return repo_id
            except Exception:
                continue
    except Exception:
        # Fall back to the first candidate; a later load() will error clearly.
        return candidates[0]

    raise RuntimeError("Could not find any candidate MLX model on the Hub")


def _test_mlx(model_id: str) -> None:
    from stonks_cli.llm.backends import ChatMessage, MLXBackend

    backend = MLXBackend(model_id, offline=False, max_new_tokens=48, temperature=0.0)
    chunks = list(
        backend.stream_chat(
            [
                ChatMessage(role="system", content="You are a helpful assistant."),
                ChatMessage(role="user", content="Say a single short word."),
            ]
        )
    )
    out = "".join(chunks).strip()
    if not out:
        raise RuntimeError("empty output")


def _pick_gguf_from_repo(repo_id: str) -> str:
    """Pick a reasonably small-ish GGUF filename from a repo.

    Prefer q4_0 if available, otherwise fall back to q8_0, otherwise any .gguf.
    """

    from huggingface_hub import HfApi

    info = HfApi().model_info(repo_id)
    filenames = [s.rfilename for s in getattr(info, "siblings", []) if getattr(s, "rfilename", "").endswith(".gguf")]
    if not filenames:
        raise RuntimeError(f"No .gguf files found in repo {repo_id}")

    def pick(pattern: str) -> str | None:
        for f in filenames:
            if pattern in f.lower():
                return f
        return None

    return pick("q4_0") or pick("q8_0") or filenames[0]


def _download_gguf(repo_id: str, filename: str) -> Path:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(repo_id=repo_id, filename=filename)
    return Path(path)


def _test_llama_cpp(repo_id: str) -> None:
    from stonks_cli.llm.backends import ChatMessage, LlamaCppBackend

    filename = _pick_gguf_from_repo(repo_id)
    gguf_path = _download_gguf(repo_id, filename)

    backend = LlamaCppBackend(str(gguf_path), max_new_tokens=64, temperature=0.0)
    chunks = list(
        backend.stream_chat(
            [
                ChatMessage(role="system", content="You are a helpful assistant."),
                ChatMessage(role="user", content="What is 2+2? Answer with just the number."),
            ]
        )
    )
    out = "".join(chunks).strip()
    if not out:
        raise RuntimeError("empty output")


def main() -> int:
    _ensure_macos()

    p = argparse.ArgumentParser(description="Smoke-test MLX / llama.cpp / Transformers backends on macOS")
    p.add_argument("--backend", choices=["all", "mlx", "llama_cpp", "transformers"], default="all")
    p.add_argument(
        "--mlx-model",
        default="auto",
        help="HF repo id for MLX model. Use 'auto' to try a few small candidates.",
    )
    p.add_argument(
        "--transformers-model",
        default="sshleifer/tiny-gpt2",
        help="HF repo id for Transformers model (tiny by default).",
    )
    p.add_argument(
        "--llama-repo",
        default="Qwen/Qwen2-0.5B-Instruct-GGUF",
        help="HF repo id containing GGUF(s) for llama.cpp.",
    )

    args = p.parse_args()

    root = _project_root()
    cache_root = _setup_local_hf_cache(root)
    print(f"Using HF cache at: {cache_root}")

    ok = True

    if args.backend in {"all", "transformers"}:
        try:
            _test_transformers(args.transformers_model)
            _print_ok("transformers", f"model={args.transformers_model}")
        except Exception as e:
            ok = False
            _print_err("transformers", e)

    if args.backend in {"all", "mlx"}:
        try:
            mlx_model = args.mlx_model
            if mlx_model == "auto":
                mlx_model = _pick_first_existing_hf_model(
                    [
                        "mlx-community/Qwen2.5-0.5B-Instruct-4bit",
                        "mlx-community/Qwen2-0.5B-Instruct-4bit",
                        "mlx-community/Llama-3.2-1B-Instruct-4bit",
                        "mlx-community/TinyLlama-1.1B-Chat-v1.0-4bit",
                    ]
                )
            _test_mlx(mlx_model)
            _print_ok("mlx", f"model={mlx_model}")
        except Exception as e:
            ok = False
            _print_err("mlx", e)

    if args.backend in {"all", "llama_cpp"}:
        try:
            _test_llama_cpp(args.llama_repo)
            _print_ok("llama_cpp", f"repo={args.llama_repo}")
        except Exception as e:
            ok = False
            _print_err("llama_cpp", e)

    if not ok:
        print("One or more backends failed. See errors above.")
        return 1

    print("All selected backends passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
