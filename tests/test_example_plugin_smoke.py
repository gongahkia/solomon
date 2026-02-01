from stonks_cli.plugins import load_plugins


def test_example_plugin_loads():
    registry = load_plugins(("asset/reference/example_plugin.py",))
    assert "example_sma20" in (registry.strategies or {})
    assert "local_csv" in (registry.provider_factories or {})
