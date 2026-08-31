# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterable


class InjectedOperationFailure(RuntimeError):
    """Test-only interruption raised at a named, predeclared persistence boundary."""


class OperationFailureInjector:
    """Disabled-by-default deterministic test fixture; it is not exposed through public inputs."""

    def __init__(self, points: Iterable[str] = ()) -> None:
        self._remaining = set(points)

    def hit(self, point: str) -> None:
        if point in self._remaining:
            self._remaining.remove(point)
            raise InjectedOperationFailure(point)


__all__ = ["InjectedOperationFailure", "OperationFailureInjector"]
