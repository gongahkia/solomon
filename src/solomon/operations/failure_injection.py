# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import signal
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


class SubprocessKillOperationFailureInjector(OperationFailureInjector):
    """Test-only hard process termination used exclusively by bounded subprocess crash proofs."""

    def hit(self, point: str) -> None:
        if point in self._remaining:
            self._remaining.remove(point)
            os.kill(os.getpid(), signal.SIGKILL)
        super().hit(point)


__all__ = ["InjectedOperationFailure", "OperationFailureInjector", "SubprocessKillOperationFailureInjector"]
