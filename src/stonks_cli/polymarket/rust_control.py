from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from stonks_cli.config import AppConfig, load_config
from stonks_cli.paths import default_state_dir


def rust_workspace_root() -> Path:
    return Path(__file__).resolve().parents[3] / "rust"


def rust_binary_path(workspace: Path | None = None) -> Path:
    root = workspace or rust_workspace_root()
    return root / "target" / "debug" / "stonks-polymarket-hotpath"


def rust_control_call(
    op: str,
    *,
    args: dict[str, Any] | None = None,
    cfg: AppConfig | None = None,
    state_dir: Path | None = None,
) -> Any:
    use_cfg = cfg or load_config()
    use_state_dir = state_dir or default_state_dir()
    workspace = rust_workspace_root()
    binary = rust_binary_path(workspace)
    use_cargo = use_cfg.polymarket.rust_hotpath_use_cargo or not binary.exists()
    cmd = (
        ["cargo", "run", "--quiet", "--bin", "stonks-polymarket-hotpath", "--", "control", op]
        if use_cargo
        else [str(binary), "control", op]
    )
    payload = {
        "state_dir": str(use_state_dir),
        "config": use_cfg.polymarket.model_dump(mode="json"),
        "args": args or {},
    }
    completed = subprocess.run(
        cmd,
        cwd=workspace,
        input=json.dumps(payload, default=str),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"rust control failed: {op}"
        raise RuntimeError(detail)
    text = completed.stdout.strip()
    if not text:
        return None
    return json.loads(text)
