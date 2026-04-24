from __future__ import annotations

import json
from pathlib import Path

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.rust_control import rust_control_call


def test_rust_control_uses_binary_when_available(monkeypatch, tmp_path):
    from stonks_cli.polymarket import rust_control

    workspace = tmp_path / "rust"
    binary = workspace / "target" / "debug" / "stonks-polymarket-hotpath"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(rust_control, "rust_workspace_root", lambda: workspace)

    class _Completed:
        returncode = 0
        stdout = json.dumps({"ok": True})
        stderr = ""

    def _run(cmd, cwd, input, capture_output, text, check):
        assert cmd == [str(binary), "control", "scan"]
        assert cwd == workspace
        payload = json.loads(input)
        assert payload["args"] == {"limit": 5}
        assert payload["state_dir"] == str(tmp_path / "state")
        return _Completed()

    monkeypatch.setattr(rust_control.subprocess, "run", _run)

    result = rust_control_call(
        "scan",
        args={"limit": 5},
        cfg=AppConfig(polymarket=PolymarketConfig(rust_hotpath_use_cargo=False)),
        state_dir=tmp_path / "state",
    )

    assert result == {"ok": True}


def test_rust_control_uses_cargo_when_binary_missing(monkeypatch, tmp_path):
    from stonks_cli.polymarket import rust_control

    workspace = tmp_path / "rust"
    workspace.mkdir()
    monkeypatch.setattr(rust_control, "rust_workspace_root", lambda: workspace)

    class _Completed:
        returncode = 0
        stdout = "[]"
        stderr = ""

    def _run(cmd, cwd, input, capture_output, text, check):
        assert cmd == ["cargo", "run", "--quiet", "--bin", "stonks-polymarket-hotpath", "--", "control", "wallet_targets"]
        assert cwd == workspace
        return _Completed()

    monkeypatch.setattr(rust_control.subprocess, "run", _run)

    result = rust_control_call(
        "wallet_targets",
        cfg=AppConfig(polymarket=PolymarketConfig(rust_hotpath_use_cargo=False)),
        state_dir=tmp_path / "state",
    )

    assert result == []


def test_rust_control_raises_on_failure(monkeypatch, tmp_path):
    from stonks_cli.polymarket import rust_control

    workspace = tmp_path / "rust"
    workspace.mkdir()
    monkeypatch.setattr(rust_control, "rust_workspace_root", lambda: workspace)

    class _Completed:
        returncode = 1
        stdout = ""
        stderr = "boom"

    def _run(*args, **kwargs):
        return _Completed()

    monkeypatch.setattr(rust_control.subprocess, "run", _run)

    try:
        rust_control_call(
            "runtime_loop",
            cfg=AppConfig(polymarket=PolymarketConfig(rust_hotpath_use_cargo=True)),
            state_dir=Path("/tmp/state"),
        )
    except RuntimeError as exc:
        assert "boom" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_rust_control_uses_cargo_when_binary_is_stale(monkeypatch, tmp_path):
    from stonks_cli.polymarket import rust_control

    workspace = tmp_path / "rust"
    src_dir = workspace / "hotpath" / "src"
    binary = workspace / "target" / "debug" / "stonks-polymarket-hotpath"
    src_dir.mkdir(parents=True)
    binary.parent.mkdir(parents=True)
    (workspace / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (workspace / "Cargo.lock").write_text("", encoding="utf-8")
    (workspace / "hotpath" / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.1.0'\n", encoding="utf-8")
    (src_dir / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(rust_control, "rust_workspace_root", lambda: workspace)

    import os
    import time

    old = time.time() - 60
    os.utime(binary, (old, old))

    class _Completed:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def _run(cmd, cwd, input, capture_output, text, check):
        assert cmd[:2] == ["cargo", "run"]
        assert cwd == workspace
        return _Completed()

    monkeypatch.setattr(rust_control.subprocess, "run", _run)

    rust_control.rust_control_call(
        "doctor",
        cfg=AppConfig(polymarket=PolymarketConfig(rust_hotpath_use_cargo=False)),
        state_dir=tmp_path / "state",
    )
