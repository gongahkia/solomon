import pytest

from stonks_cli.vnext.alert_subscriptions import AlertSubscription


def test_alert_subscription_models_enabled_canonical_event_delivery_preferences_without_delivery_behavior():
    subscription = AlertSubscription("daily-risk", "-100123", frozenset({"daily_report", "risk.limit_breach"}))

    assert subscription.enabled is True
    assert subscription.event_types == frozenset({"daily_report", "risk.limit_breach"})


def test_alert_subscription_fails_closed_for_missing_or_malformed_fields():
    with pytest.raises(ValueError, match="event types"):
        AlertSubscription("daily-risk", "-100123", frozenset())
    with pytest.raises(ValueError, match="event types"):
        AlertSubscription("daily-risk", "-100123", frozenset({"Risk Report"}))
    with pytest.raises(ValueError, match="enabled state"):
        AlertSubscription("daily-risk", "-100123", frozenset({"daily_report"}), 1)
