from __future__ import annotations

import importlib


def test_auto_does_not_pick_mlx_when_model_not_hf_repo(monkeypatch):
    backends = importlib.import_module("stonks_cli.llm.backends")

    # Pretend we're on macOS arm64 with mlx-lm installed.
    monkeypatch.setattr(backends, "_is_macos_arm64", lambda: True)

    def fake_has_module(name: str) -> bool:
        return name in {"mlx_lm"}

    monkeypatch.setattr(backends, "_has_module", fake_has_module)

    # Default config model name like "gemma3" is not an HF repo id and no local path.
    selected = backends._select_backend("auto", offline=False, model="gemma3", path=None)
    assert selected == "ollama"


def test_auto_picks_mlx_when_hf_repo_id_and_mlx_installed(monkeypatch):
    backends = importlib.import_module("stonks_cli.llm.backends")

    monkeypatch.setattr(backends, "_is_macos_arm64", lambda: True)

    def fake_has_module(name: str) -> bool:
        return name in {"mlx_lm"}

    monkeypatch.setattr(backends, "_has_module", fake_has_module)

    selected = backends._select_backend(
        "auto",
        offline=False,
        model="mlx-community/Llama-3.2-3B-Instruct-4bit",
        path=None,
    )
    assert selected == "mlx"


def test_coerce_model_ref_defaults(monkeypatch):
    backends = importlib.import_module("stonks_cli.llm.backends")

    class DummyCfg:
        path = None
        model = "gemma3"  # Ollama-ish default, not HF repo id

    assert backends._coerce_model_ref("mlx", DummyCfg()) == "mlx-community/Llama-3.2-3B-Instruct-4bit"
    assert backends._coerce_model_ref("transformers", DummyCfg()) == "TinyLlama/TinyLlama-1.1B-Chat-v1.0"


def test_offline_prefers_local_backends(monkeypatch, tmp_path):
    backends = importlib.import_module("stonks_cli.llm.backends")

    gguf = tmp_path / "model.gguf"
    gguf.write_text("not a real model")

    def fake_has_module(name: str) -> bool:
        return name in {"llama_cpp", "mlx_lm", "transformers"}

    monkeypatch.setattr(backends, "_has_module", fake_has_module)
    monkeypatch.setattr(backends, "_is_macos_arm64", lambda: True)

    # Offline: if a local gguf path exists and llama_cpp is installed, prefer llama_cpp.
    selected = backends._select_backend("auto", offline=True, model="", path=str(gguf))
    assert selected == "llama_cpp"
