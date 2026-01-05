import pytest

from stonks_cli.plugins import load_plugins


def test_plugin_strategy_return_type_is_validated(tmp_path):
    plugin_path = tmp_path / "bad_plugin.py"
    plugin_path.write_text(
        """
def bad_strategy(df):
    return 'not a recommendation'

STONKS_STRATEGIES = {'bad': bad_strategy}
""".lstrip(),
        encoding="utf-8",
    )

    registry = load_plugins((str(plugin_path),))
    with pytest.raises(TypeError) as ei:
        registry.strategies["bad"](object())
    assert "must return Recommendation" in str(ei.value)
