import pytest

from stonks_cli.vnext.errors import VNextExecutionDeniedError, VNextExternalDataError
from stonks_cli.vnext.opend_fixture import RecordedOpenDCall, RecordedOpenDFixtureAdapter


def test_recorded_opend_fixture_replays_exact_read_calls_and_requires_consumption():
    adapter = RecordedOpenDFixtureAdapter("127.0.0.1", 11111, (RecordedOpenDCall("get_acc_list", (), (), (0, [])),))
    context = adapter.context_factory("127.0.0.1", 11111)
    assert context.get_acc_list() == (0, [])
    context.close()


def test_recorded_opend_fixture_denies_mutation_and_request_mismatches():
    context = RecordedOpenDFixtureAdapter("127.0.0.1", 11111, (RecordedOpenDCall("get_stock_quote", (("US.AAPL",),), (), (0, [])),)).context_factory("127.0.0.1", 11111)
    with pytest.raises(VNextExecutionDeniedError):
        context.place_order()
    with pytest.raises(VNextExternalDataError):
        context.get_stock_quote(["US.AAPL"])
    with pytest.raises(VNextExternalDataError, match="unconsumed"):
        context.close()
