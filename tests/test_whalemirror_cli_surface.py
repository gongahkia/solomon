from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

from stonks_cli.cli import app

ROOT = Path(__file__).resolve().parents[1]


def test_root_help_points_to_whalemirror_not_equity_surfaces():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "whalemirror" in result.output
    assert "Hyperliquid paper-first" in result.output
    assert "analyze" not in result.output
    assert "data" not in result.output
    assert "report" not in result.output
    assert "history" not in result.output
    assert "research" not in result.output
    assert "polymarket" not in result.output


def test_whalemirror_demo_is_visible_subcommand():
    result = CliRunner().invoke(app, ["whalemirror", "--help"])

    assert result.exit_code == 0
    assert "ledger-demo" in result.output
    assert "fixture-backed public ledger" in result.output


def test_stock_provider_extras_and_mcp_example_are_removed():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]

    assert set(extras) == {"dev"}
    assert not (ROOT / "mcp-config.example.json").exists()
