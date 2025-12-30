from stonks.analysis.risk import suggest_position_fraction_by_volatility


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
