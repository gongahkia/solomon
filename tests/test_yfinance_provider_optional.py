from __future__ import annotations

import importlib

import pytest

from stonks_cli.data.providers import YFinanceProvider


def test_yfinance_provider_requires_optional_dependency(monkeypatch):
    real_import = importlib.import_module

    def fake_import(name: str, package=None):
        if name == "yfinance":
            raise ImportError("nope")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    p = YFinanceProvider()
    with pytest.raises(ImportError):
        p.fetch_daily("AAPL")
