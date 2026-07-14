import pytest

from stonks_cli.vnext.errors import OpenDQuotaExceededError, VNextInvariantError
from stonks_cli.vnext.rate_limit import ReadOnlyRateLimiter


def test_read_only_rate_limiter_enforces_window_without_sleeping():
    now = [0.0]
    limiter = ReadOnlyRateLimiter(2, 30, clock=lambda: now[0])
    limiter.acquire()
    limiter.acquire()
    with pytest.raises(OpenDQuotaExceededError):
        limiter.acquire()
    now[0] = 30
    limiter.acquire()


def test_read_only_rate_limiter_fails_closed_on_backward_clock():
    now = [1.0]
    limiter = ReadOnlyRateLimiter(1, 30, clock=lambda: now[0])
    limiter.acquire()
    now[0] = 0.0
    with pytest.raises(VNextInvariantError):
        limiter.acquire()
