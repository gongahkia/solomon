from functools import partial

from stonks_cli.config import AppConfig
from stonks_cli.pipeline import select_strategy


def test_strategy_params_wraps_sma_cross_with_partial() -> None:
    cfg = AppConfig(strategy="sma_cross", strategy_params={"fast": 10, "slow": 30})
    fn = select_strategy(cfg)
    assert isinstance(fn, partial)
    assert fn.func.__name__ == "sma_cross_strategy"
    assert fn.keywords == {"fast": 10, "slow": 30}
