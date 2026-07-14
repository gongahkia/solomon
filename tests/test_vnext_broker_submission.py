from __future__ import annotations

import pytest

from stonks_cli.vnext.broker_submission import BLOCKED_BROKER_SUBMISSION_METHODS, require_read_only_broker_method
from stonks_cli.vnext.errors import VNextExecutionDeniedError
from stonks_cli.vnext.opend_fixture import RecordedOpenDCall, RecordedOpenDFixtureAdapter


def test_broker_submission_methods_are_all_denied_before_any_adapter_call():
    for method in BLOCKED_BROKER_SUBMISSION_METHODS:
        with pytest.raises(VNextExecutionDeniedError, match=f"broker method is prohibited:{method}"):
            require_read_only_broker_method(method)


def test_read_only_broker_method_is_preserved_for_fixture_replay():
    assert require_read_only_broker_method("get_stock_quote") == "get_stock_quote"
    adapter = RecordedOpenDFixtureAdapter("127.0.0.1", 11111, (RecordedOpenDCall("get_stock_quote", (), (), (0, [])),))
    context = adapter.context_factory("127.0.0.1", 11111)

    assert context.get_stock_quote() == (0, [])
    context.close()


@pytest.mark.parametrize("method", [None, "", "get-stock-quote", "Place_Order"])
def test_broker_submission_guard_fails_closed_for_malformed_external_method_names(method):
    with pytest.raises(ValueError, match="broker method name is invalid"):
        require_read_only_broker_method(method)


def test_recorded_opend_fixture_rejects_blocked_submission_methods_at_record_and_call_time():
    with pytest.raises(ValueError, match="non-mutating"):
        RecordedOpenDCall("place_order", (), (), None)

    context = RecordedOpenDFixtureAdapter("127.0.0.1", 11111, ()).context_factory("127.0.0.1", 11111)
    with pytest.raises(VNextExecutionDeniedError, match="broker method is prohibited:cancel_order"):
        context.cancel_order()
