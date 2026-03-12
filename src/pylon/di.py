"""Lightweight dependency-injection container for Pylon composition roots."""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


ServiceKey = Hashable


@runtime_checkable
class Resolver(Protocol):
    """Runtime dependency resolver."""

    def resolve(self, key: ServiceKey) -> Any: ...

    def resolve_optional(self, key: ServiceKey, default: Any = None) -> Any: ...


class DependencyLifetime(StrEnum):
    """Supported lifetimes for registered services."""

    SINGLETON = "singleton"
    SCOPED = "scoped"
    TRANSIENT = "transient"


@dataclass(frozen=True)
class _Registration:
    lifetime: DependencyLifetime
    factory: Callable[[Resolver], Any]


class ServiceScope(Resolver):
    """Per-request or ad-hoc scope for scoped services."""

    def __init__(self, container: ServiceContainer) -> None:
        self._container = container
        self._instances: dict[ServiceKey, Any] = {}
        self._lock = threading.RLock()

    def resolve(self, key: ServiceKey) -> Any:
        return self._container._resolve(key, scope=self)

    def resolve_optional(self, key: ServiceKey, default: Any = None) -> Any:
        try:
            return self.resolve(key)
        except KeyError:
            return default


class ServiceContainer(Resolver):
    """Minimal DI container with singleton, scoped, and transient lifetimes."""

    def __init__(self) -> None:
        self._registrations: dict[ServiceKey, _Registration] = {}
        self._singletons: dict[ServiceKey, Any] = {}
        self._lock = threading.RLock()
        self._root_scope = ServiceScope(self)

    def has(self, key: ServiceKey) -> bool:
        with self._lock:
            return key in self._registrations

    def register_instance(self, key: ServiceKey, instance: Any) -> None:
        self.register_factory(
            key,
            lambda _resolver: instance,
            lifetime=DependencyLifetime.SINGLETON,
        )
        with self._lock:
            self._singletons[key] = instance

    def register_factory(
        self,
        key: ServiceKey,
        factory: Callable[[Resolver], Any],
        *,
        lifetime: DependencyLifetime = DependencyLifetime.TRANSIENT,
    ) -> None:
        with self._lock:
            self._registrations[key] = _Registration(
                lifetime=lifetime,
                factory=factory,
            )
            self._singletons.pop(key, None)

    def register_singleton(
        self,
        key: ServiceKey,
        factory: Callable[[Resolver], Any],
    ) -> None:
        self.register_factory(key, factory, lifetime=DependencyLifetime.SINGLETON)

    def register_scoped(
        self,
        key: ServiceKey,
        factory: Callable[[Resolver], Any],
    ) -> None:
        self.register_factory(key, factory, lifetime=DependencyLifetime.SCOPED)

    def override(self, key: ServiceKey, instance: Any) -> None:
        self.register_instance(key, instance)

    def create_scope(self) -> ServiceScope:
        return ServiceScope(self)

    def resolve(self, key: ServiceKey) -> Any:
        return self._resolve(key, scope=self._root_scope)

    def resolve_optional(self, key: ServiceKey, default: Any = None) -> Any:
        try:
            return self.resolve(key)
        except KeyError:
            return default

    def _resolve(self, key: ServiceKey, *, scope: ServiceScope) -> Any:
        with self._lock:
            registration = self._registrations.get(key)
            if registration is None:
                raise KeyError(f"Dependency not registered: {key!r}")
            if registration.lifetime is DependencyLifetime.SINGLETON:
                if key not in self._singletons:
                    self._singletons[key] = registration.factory(self)
                return self._singletons[key]

        if registration.lifetime is DependencyLifetime.SCOPED:
            with scope._lock:
                if key not in scope._instances:
                    scope._instances[key] = registration.factory(scope)
                return scope._instances[key]

        return registration.factory(scope)
