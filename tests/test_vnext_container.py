from __future__ import annotations

import pytest

from stonks_cli.vnext.container import ServiceContainer
from stonks_cli.vnext.errors import VNextInvariantError


class ClockService:
    pass


class ReportService:
    def __init__(self, clock: ClockService) -> None:
        self.clock = clock


def test_service_container_resolves_singletons_and_explicit_dependencies():
    container = ServiceContainer()
    calls = 0

    def create_clock(_: ServiceContainer) -> object:
        nonlocal calls
        calls += 1
        return ClockService()

    container.register_factory(ClockService, create_clock)
    container.register_factory(ReportService, lambda services: ReportService(services.resolve(ClockService)))

    report = container.resolve(ReportService)

    assert isinstance(report, ReportService)
    assert isinstance(report.clock, ClockService)
    assert container.resolve(ReportService) is report
    assert calls == 1


def test_service_container_rejects_unregistered_duplicate_and_sealed_services():
    container = ServiceContainer()
    with pytest.raises(KeyError, match="unregistered service:ClockService"):
        container.resolve(ClockService)

    container.register_instance(ClockService, ClockService())
    with pytest.raises(VNextInvariantError, match="service already registered"):
        container.register_instance(ClockService, ClockService())
    container.seal()
    with pytest.raises(VNextInvariantError, match="service container is sealed"):
        container.register_factory(ReportService, lambda _: ReportService(ClockService()))


def test_service_container_fails_closed_for_wrong_type_and_circular_dependencies():
    container = ServiceContainer()
    container.register_factory(ClockService, lambda _: ReportService(ClockService()))
    with pytest.raises(VNextInvariantError, match="service factory returned wrong type"):
        container.resolve(ClockService)

    first = ServiceContainer()
    first.register_factory(ClockService, lambda services: services.resolve(ReportService))
    first.register_factory(ReportService, lambda services: services.resolve(ClockService))
    with pytest.raises(VNextInvariantError, match="circular service dependency"):
        first.resolve(ClockService)
