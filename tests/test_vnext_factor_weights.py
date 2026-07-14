import math

import pytest

from stonks_cli.config import AppConfig


def test_research_factor_weights_are_complete_normalized_and_canonically_ordered():
    config = AppConfig.model_validate(
        {
            "vnext": {
                "research": {
                    "factor_weights": {
                        "weights": {
                            "risk_adjusted_performance": 0.1,
                            "mean_reversion": 0.2,
                            "trend": 0.3,
                            "momentum": 0.4,
                        }
                    }
                }
            }
        }
    )

    assert config.vnext.research.factor_weights.ordered_items() == (
        ("trend", 0.3),
        ("momentum", 0.4),
        ("mean_reversion", 0.2),
        ("risk_adjusted_performance", 0.1),
    )


@pytest.mark.parametrize(
    "weights",
    (
        {"trend": 0.25, "momentum": 0.25, "mean_reversion": 0.25},
        {"trend": 0.3, "momentum": 0.3, "mean_reversion": 0.3, "risk_adjusted_performance": 0.3},
        {"trend": 0.25, "momentum": -0.25, "mean_reversion": 0.5, "risk_adjusted_performance": 0.5},
        {"trend": math.nan, "momentum": 0.25, "mean_reversion": 0.25, "risk_adjusted_performance": 0.25},
        {"trend": "0.25", "momentum": 0.25, "mean_reversion": 0.25, "risk_adjusted_performance": 0.25},
    ),
)
def test_research_factor_weights_fail_closed_for_incomplete_or_invalid_configuration(weights):
    with pytest.raises(ValueError):
        AppConfig.model_validate({"vnext": {"research": {"factor_weights": {"weights": weights}}}})
