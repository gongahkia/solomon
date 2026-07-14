from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

from stonks_cli.cli import app

ROOT = Path(__file__).resolve().parents[1]


def test_root_help_uses_stonks_cli_flat_surface():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Stonks CLI" in result.output
    assert "replay-ingest" in result.output
    assert "scan-carry" in result.output
    assert "research" not in result.output.lower()
    assert "polymarket" not in result.output


def test_ledger_demo_is_visible_at_root():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "demo-ledger" in result.output
    assert "fixture-backed public ledger" in result.output


def test_retired_grouped_commands_are_unknown():
    for command in (["research"], ["carry", "scan"], ["config", "show"]):
        result = CliRunner().invoke(app, command)

        assert result.exit_code == 2


def test_stock_provider_extras_and_mcp_example_are_removed():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]

    assert set(extras) == {"dev"}
    assert not (ROOT / "mcp-config.example.json").exists()
