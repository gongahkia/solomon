from __future__ import annotations


def test_whalemirror_imports():
    from stonks_cli.whalemirror import MirrorMode, Venue, evaluate_execution_guards
    assert Venue.HYPERLIQUID == "hyperliquid"
    assert MirrorMode.PAPER == "paper"
    guards = evaluate_execution_guards(venue=Venue.HYPERLIQUID, mode=MirrorMode.PAPER)
    assert guards == []


def test_cli_import():
    from stonks_cli.cli import app
    assert app is not None
