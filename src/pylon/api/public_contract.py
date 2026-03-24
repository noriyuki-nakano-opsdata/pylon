"""Public API contract helpers for canonical route registration and product features."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pylon.api.server import APIServer, HandlerFunc, Request, Response

API_V1_PREFIX = "/api/v1"
CONTRACT_VERSION = "2026-03-11"
LEGACY_ALIAS_DEPRECATED_ON = CONTRACT_VERSION
LEGACY_ALIAS_SUNSET_ON = "2026-09-30"


@dataclass(frozen=True)
class PublicRouteSpec:
    """Machine-readable description of one canonical public route."""

    method: str
    canonical_path: str
    aliases: tuple[str, ...] = ()
    any_of_scopes: tuple[str, ...] = ()
    all_of_scopes: tuple[str, ...] = ()


@dataclass
class PublicContractRegistry:
    """Collect canonical public-route metadata as routes are registered."""

    routes: list[PublicRouteSpec] = field(default_factory=list)

    def add(
        self,
        method: str,
        canonical_path: str,
        *,
        aliases: tuple[str, ...] = (),
        any_of_scopes: tuple[str, ...] = (),
        all_of_scopes: tuple[str, ...] = (),
    ) -> None:
        self.routes.append(
            PublicRouteSpec(
                method=method.upper(),
                canonical_path=canonical_path,
                aliases=tuple(aliases),
                any_of_scopes=tuple(any_of_scopes),
                all_of_scopes=tuple(all_of_scopes),
            )
        )

    def manifest(self) -> dict[str, Any]:
        """Return the canonical public API contract as JSON-serializable data."""
        sorted_routes = sorted(
            self.routes,
            key=lambda route: (route.canonical_path, route.method),
        )
        return {
            "contract_version": CONTRACT_VERSION,
            "canonical_prefix": API_V1_PREFIX,
            "legacy_aliases_enabled": any(route.aliases for route in sorted_routes),
            "legacy_alias_policy": {
                "deprecated_on": LEGACY_ALIAS_DEPRECATED_ON,
                "sunset_on": LEGACY_ALIAS_SUNSET_ON,
            },
            "routes": [
                {
                    "method": route.method,
                    "path": route.canonical_path,
                    "aliases": [
                        {
                            "path": alias,
                            "deprecated": True,
                            "deprecated_on": LEGACY_ALIAS_DEPRECATED_ON,
                            "sunset_on": LEGACY_ALIAS_SUNSET_ON,
                        }
                        for alias in route.aliases
                    ],
                    "authorization": {
                        "any_of_scopes": list(route.any_of_scopes),
                        "all_of_scopes": list(route.all_of_scopes),
                    },
                }
                for route in sorted_routes
            ],
        }


def v1(path: str) -> str:
    """Prefix a relative public path with the canonical v1 API namespace."""
    if not path.startswith("/"):
        msg = "Public API paths must start with '/'"
        raise ValueError(msg)
    return f"{API_V1_PREFIX}{path}"


def _legacy_alias_handler(
    handler: HandlerFunc,
    *,
    canonical_path: str,
    alias_path: str,
) -> HandlerFunc:
    """Wrap a compatibility alias handler with deprecation response headers."""

    def wrapped(request: Request) -> Response:
        response = handler(request)
        headers = dict(response.headers)
        existing_link = headers.get("link", "")
        successor_link = f"<{canonical_path}>; rel=\"successor-version\""
        headers.setdefault("deprecation", "true")
        headers.setdefault("sunset", LEGACY_ALIAS_SUNSET_ON)
        headers["link"] = (
            f"{existing_link}, {successor_link}" if existing_link else successor_link
        )
        headers.setdefault("x-pylon-canonical-path", canonical_path)
        headers.setdefault(
            "warning",
            (
                f'299 - "Deprecated API alias {alias_path}; use {canonical_path} '
                f"before {LEGACY_ALIAS_SUNSET_ON}\""
            ),
        )
        response.headers = headers
        return response

    return wrapped


def register_public_route(
    server: APIServer,
    method: str,
    canonical_path: str,
    handler: HandlerFunc,
    *,
    aliases: tuple[str, ...] = (),
    any_of_scopes: tuple[str, ...] = (),
    all_of_scopes: tuple[str, ...] = (),
    registry: PublicContractRegistry | None = None,
) -> None:
    """Register one canonical public route and optional compatibility aliases."""
    if registry is not None:
        registry.add(
            method,
            canonical_path,
            aliases=aliases,
            any_of_scopes=any_of_scopes,
            all_of_scopes=all_of_scopes,
        )
    server.add_route(method, canonical_path, handler)
    for alias in aliases:
        server.add_route(
            method,
            alias,
            _legacy_alias_handler(
                handler,
                canonical_path=canonical_path,
                alias_path=alias,
            ),
        )


@dataclass(frozen=True)
class SurfaceGroup:
    admin: dict[str, bool] = field(default_factory=dict)
    project: dict[str, bool] = field(default_factory=dict)


def build_feature_manifest() -> dict[str, Any]:
    """Return the product surfaces exposed by the reference implementation."""
    surfaces = SurfaceGroup(
        admin={
            "dashboard": True,
            "workflows": True,
            "agents": True,
            "costs": True,
            "providers": True,
            "models": True,
            "skills": True,
            "settings": True,
        },
        project={
            "runs": True,
            "approvals": True,
            "experiments": True,
            "studio": False,
            "lifecycle": True,
            "gtm": True,
            "tasks": True,
            "team": True,
            "memory": True,
            "calendar": True,
            "content": True,
            "ads": True,
            "issues": False,
            "pulls": False,
            "tsumiki_requirements": True,
            "tsumiki_reverse_engineering": True,
            "tsumiki_task_decomposition": True,
            "tsumiki_dcs_analysis": True,
            "tsumiki_technical_design": True,
        },
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "canonical_prefix": API_V1_PREFIX,
        "legacy_aliases_enabled": True,
        "legacy_alias_policy": {
            "deprecated_on": LEGACY_ALIAS_DEPRECATED_ON,
            "sunset_on": LEGACY_ALIAS_SUNSET_ON,
        },
        "contract_path": v1("/contract"),
        "surfaces": {
            "admin": dict(surfaces.admin),
            "project": dict(surfaces.project),
        },
    }
