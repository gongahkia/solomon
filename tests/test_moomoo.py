from __future__ import annotations

from stonks_cli.moomoo import MoomooReadOnlyProvider, OpenDConnection


class Context:
    def __init__(self) -> None:
        self.closed = False

    def get_acc_list(self):
        return 0, [{"acc_id": 2, "acc_index": 1, "trd_env": "REAL"}]

    def close(self) -> None:
        self.closed = True


def test_moomoo_reads_accounts_from_loopback_context() -> None:
    contexts: list[Context] = []

    def factory(_: str, __: int) -> Context:
        context = Context()
        contexts.append(context)
        return context

    accounts = MoomooReadOnlyProvider(OpenDConnection(), factory).accounts()
    assert accounts[0].account_id == "2"
    assert contexts[0].closed is True


def test_moomoo_rejects_non_loopback_endpoint() -> None:
    try:
        OpenDConnection("10.0.0.1", 11111)
    except Exception as error:
        assert "loopback" in str(error)
    else:
        raise AssertionError("non-loopback endpoint must be rejected")
