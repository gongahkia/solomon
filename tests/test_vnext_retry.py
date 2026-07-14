import pytest

from stonks_cli.vnext.errors import OpenDEndpointUnavailableError, OpenDResponseMalformedError
from stonks_cli.vnext.retry import IdempotentReadRetryPolicy, retry_idempotent_read


def test_retry_idempotent_read_retries_only_explicit_retryable_external_errors():
    outcomes = iter([OpenDEndpointUnavailableError(), "ok"])
    delays: list[float] = []

    result = retry_idempotent_read(
        lambda: (_raise_or_return(next(outcomes))),
        IdempotentReadRetryPolicy(2, (0.5,)),
        is_retryable=lambda error: isinstance(error, OpenDEndpointUnavailableError),
        sleep=delays.append,
    )

    assert result == "ok"
    assert delays == [0.5]


def test_retry_idempotent_read_does_not_retry_non_retryable_errors():
    with pytest.raises(OpenDResponseMalformedError):
        retry_idempotent_read(
            lambda: (_raise_or_return(OpenDResponseMalformedError())),
            IdempotentReadRetryPolicy(2, (0,)),
            is_retryable=lambda error: isinstance(error, OpenDEndpointUnavailableError),
            sleep=lambda delay: pytest.fail("sleep should not run"),
        )


def _raise_or_return(value):
    if isinstance(value, Exception):
        raise value
    return value
