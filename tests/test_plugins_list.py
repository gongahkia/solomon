import json

from stonks_cli.commands import do_plugins_list


def test_plugins_list_discovers_strategies_and_providers(monkeypatch, tmp_path):
    plugin_path = tmp_path / "my_plugin.py"
    plugin_path.write_text(
        """
from __future__ import annotations

from stonks_cli.analysis.strategy import Recommendation


def my_strategy(df):
    return Recommendation(action='BUY_DCA', confidence=0.5, rationale='ok')


def my_provider_factory(cfg, ticker):
    return object()


STONKS_STRATEGIES = {'my_strategy': my_strategy}
STONKS_PROVIDER_FACTORIES = {'my_provider': my_provider_factory}
""".lstrip(),
        encoding="utf-8",
    )

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"plugins": [str(plugin_path)]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("STONKS_CLI_CONFIG", str(cfg_path))

    out = do_plugins_list()
    assert str(plugin_path) in (out.get("ok") or [])
    assert "my_strategy" in (out.get("strategies") or [])
    assert "my_provider" in (out.get("provider_factories") or [])
