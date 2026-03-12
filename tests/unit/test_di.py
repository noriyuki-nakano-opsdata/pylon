from __future__ import annotations

from pylon.di import DependencyLifetime, ServiceContainer


def test_service_container_reuses_singletons() -> None:
    container = ServiceContainer()
    created: list[object] = []

    def factory(_resolver: ServiceContainer) -> object:
        instance = object()
        created.append(instance)
        return instance

    container.register_factory(
        "singleton",
        factory,
        lifetime=DependencyLifetime.SINGLETON,
    )

    assert container.resolve("singleton") is container.resolve("singleton")
    assert len(created) == 1


def test_service_container_scopes_scoped_dependencies() -> None:
    container = ServiceContainer()
    container.register_factory(
        "scoped",
        lambda _resolver: object(),
        lifetime=DependencyLifetime.SCOPED,
    )

    scope_a = container.create_scope()
    scope_b = container.create_scope()

    assert scope_a.resolve("scoped") is scope_a.resolve("scoped")
    assert scope_a.resolve("scoped") is not scope_b.resolve("scoped")


def test_service_container_override_replaces_registration() -> None:
    container = ServiceContainer()
    container.register_instance("value", "old")

    container.override("value", "new")

    assert container.resolve("value") == "new"
