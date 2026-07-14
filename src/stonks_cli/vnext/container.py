from __future__ import annotations

from collections.abc import Callable

from stonks_cli.vnext.errors import VNextInvariantError

ServiceFactory = Callable[["ServiceContainer"], object]


class ServiceContainer:
    def __init__(self) -> None:
        self._factories: dict[type[object], ServiceFactory] = {}
        self._instances: dict[type[object], object] = {}
        self._resolving: set[type[object]] = set()
        self._sealed = False

    def register_instance(self, service_type: type[object], instance: object) -> None:
        self._register(service_type, lambda _: instance)

    def register_factory(self, service_type: type[object], factory: ServiceFactory) -> None:
        if not callable(factory):
            raise TypeError("service factory must be callable")
        self._register(service_type, factory)

    def seal(self) -> None:
        self._sealed = True

    def resolve(self, service_type: type[object]) -> object:
        _validate_service_type(service_type)
        if service_type in self._instances:
            return self._instances[service_type]
        factory = self._factories.get(service_type)
        if factory is None:
            raise KeyError(f"unregistered service:{service_type.__name__}")
        if service_type in self._resolving:
            raise VNextInvariantError(f"circular service dependency:{service_type.__name__}")
        self._resolving.add(service_type)
        try:
            instance = factory(self)
            if not isinstance(instance, service_type):
                raise VNextInvariantError(f"service factory returned wrong type:{service_type.__name__}")
            self._instances[service_type] = instance
            return instance
        finally:
            self._resolving.remove(service_type)

    def _register(self, service_type: type[object], factory: ServiceFactory) -> None:
        _validate_service_type(service_type)
        if self._sealed:
            raise VNextInvariantError("service container is sealed")
        if service_type in self._factories:
            raise VNextInvariantError(f"service already registered:{service_type.__name__}")
        self._factories[service_type] = factory


def _validate_service_type(service_type: object) -> None:
    if not isinstance(service_type, type):
        raise TypeError("service type must be a class")
