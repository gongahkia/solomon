from stonks.analysis.risk import (
    scale_fractions_to_portfolio_cap,
    suggest_stop_loss_price_by_atr,
    suggest_position_fraction_by_volatility,
    suggest_take_profit_price_by_atr,
)


def test_suggest_position_fraction_by_volatility_scales_inverse() -> None:
    # At reference vol, returns base fraction
    assert suggest_position_fraction_by_volatility(0.20) == 0.10

    # Higher vol -> smaller size
    hi = suggest_position_fraction_by_volatility(0.40)
    lo = suggest_position_fraction_by_volatility(0.10)
    assert hi is not None and lo is not None
    assert hi < 0.10
    assert lo > 0.10


def test_suggest_position_fraction_by_volatility_invalid() -> None:
    assert suggest_position_fraction_by_volatility(0.0) is None
    assert suggest_position_fraction_by_volatility(-1.0) is None


def test_suggest_position_fraction_by_volatility_respects_cap() -> None:
    # Extremely low vol would imply a huge position; ensure we cap it.
    capped = suggest_position_fraction_by_volatility(0.01, max_fraction=0.05)
    assert capped == 0.05


def test_scale_fractions_to_portfolio_cap_scales_down() -> None:
    scaled, factor = scale_fractions_to_portfolio_cap(
        {"A": 0.20, "B": 0.20, "C": 0.10},
        max_portfolio_exposure_fraction=0.25,
    )
    assert 0 < factor < 1
    assert abs(sum(scaled.values()) - 0.25) < 1e-9


def test_scale_fractions_to_portfolio_cap_no_scale_when_under_cap() -> None:
    scaled, factor = scale_fractions_to_portfolio_cap(
        {"A": 0.10, "B": 0.10},
        max_portfolio_exposure_fraction=0.50,
    )
    assert factor == 1.0
    assert scaled == {"A": 0.10, "B": 0.10}


def test_suggest_stop_loss_price_by_atr() -> None:
    assert suggest_stop_loss_price_by_atr(100.0, 2.0, multiple=2.0) == 96.0
    assert suggest_stop_loss_price_by_atr(100.0, 0.0) is None


def test_suggest_take_profit_price_by_atr() -> None:
    assert suggest_take_profit_price_by_atr(100.0, 2.0, multiple=3.0) == 106.0
    assert suggest_take_profit_price_by_atr(100.0, 0.0) is None
