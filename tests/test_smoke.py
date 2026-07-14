from __future__ import annotations


def test_research_imports():
    from stonks_cli.research import ExecutionMode, Venue, evaluate_execution_guards
    assert Venue.HYPERLIQUID == "hyperliquid"
    assert ExecutionMode.PAPER == "paper"
    guards = evaluate_execution_guards(venue=Venue.HYPERLIQUID, mode=ExecutionMode.PAPER)
    assert guards == []


def test_cli_import():
    from stonks_cli.cli import app
    assert app is not None
