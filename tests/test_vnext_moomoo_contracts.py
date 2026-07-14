from stonks_cli.vnext.moomoo import (
    MoomooAccount,
    MoomooAccountBalance,
    MoomooOpenDProcessContract,
    MoomooReadOnlyAccountClient,
    MoomooReadOnlyBalanceClient,
)
from stonks_cli.vnext.opend_fixture import RecordedOpenDCall, RecordedOpenDFixtureAdapter


def test_moomoo_account_adapter_contract_matches_recorded_opend_request_and_response():
    contract = MoomooOpenDProcessContract("127.0.0.1", 11111)
    fixture = RecordedOpenDFixtureAdapter(
        "127.0.0.1",
        11111,
        (RecordedOpenDCall("get_acc_list", (), (), (0, [{"acc_id": "100", "acc_index": 0, "trd_env": "REAL"}])),),
    )

    assert MoomooReadOnlyAccountClient(contract, fixture.context_factory).list_accounts() == (MoomooAccount("100", 0, "REAL"),)


def test_moomoo_balance_adapter_contract_matches_stable_account_request_and_response():
    contract = MoomooOpenDProcessContract("127.0.0.1", 11111)
    fixture = RecordedOpenDFixtureAdapter(
        "127.0.0.1",
        11111,
        (
            RecordedOpenDCall(
                "accinfo_query",
                (),
                (("trd_env", "REAL"), ("acc_id", 100), ("refresh_cache", False)),
                (0, [{"currency": "USD", "total_assets": 10, "cash": 2, "market_val": 8}]),
            ),
        ),
    )

    assert MoomooReadOnlyBalanceClient(contract, fixture.context_factory).read_balance(MoomooAccount("100", 7, "REAL")) == MoomooAccountBalance(
        "100", "USD", 10.0, 2.0, 8.0
    )
