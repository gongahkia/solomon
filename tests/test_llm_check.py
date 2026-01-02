from __future__ import annotations

import importlib
import importlib.util


def test_llm_check_auto_offline_prefers_llama_cpp_for_gguf(monkeypatch, tmp_path):
    commands = importlib.import_module("stonks_cli.commands")
    backends = importlib.import_module("stonks_cli.llm.backends")

    gguf = tmp_path / "model.gguf"
    gguf.write_text("not a real gguf")

    # Make backend selection think llama.cpp is installed; and selection doesn't depend on platform.
    monkeypatch.setattr(backends, "_has_module", lambda name: name == "llama_cpp")
    monkeypatch.setattr(backends, "_is_macos_arm64", lambda: False)

    # Make llm check's dependency probe think llama_cpp is installed.
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "llama_cpp" else None)

    out = commands.do_llm_check(backend="auto", offline=True, path=str(gguf), model="")
    assert out.startswith("ok backend=llama_cpp")
    assert "selected=llama_cpp" in out


def test_llm_check_mlx_offline_requires_directory(monkeypatch, tmp_path):
    commands = importlib.import_module("stonks_cli.commands")

    bad_file = tmp_path / "not_a_dir"
    bad_file.write_text("x")

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "mlx_lm" else None)

    out = commands.do_llm_check(backend="mlx", offline=True, path=str(bad_file), model="")
    assert out.startswith("error backend=mlx")


def test_llm_check_transformers_offline_requires_directory(monkeypatch, tmp_path):
    commands = importlib.import_module("stonks_cli.commands")

    bad_file = tmp_path / "not_a_dir"
    bad_file.write_text("x")

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "transformers" else None)

    out = commands.do_llm_check(backend="transformers", offline=True, path=str(bad_file), model="")
    assert out.startswith("error backend=transformers")


def test_llm_check_llama_cpp_requires_file(monkeypatch, tmp_path):
    commands = importlib.import_module("stonks_cli.commands")

    d = tmp_path / "model_dir"
    d.mkdir()

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "llama_cpp" else None)

    out = commands.do_llm_check(backend="llama_cpp", offline=True, path=str(d), model="")
    assert out.startswith("error backend=llama_cpp")
