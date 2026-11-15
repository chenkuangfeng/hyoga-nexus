"""Helpers for dual publishing tenant administration routes during API migration."""
from __future__ import annotations

from collections.abc import Callable
from copy import copy
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute
from starlette.routing import compile_path


def tenant_admin_route(
    router: APIRouter, path: str, *, methods: list[str], deprecated_legacy: bool = True, **options: Any,
):
    """Register a tenant admin route at its canonical path and deprecated legacy path.

    The tenant identifier remains in the same position. The canonical route inserts
    ``/admin`` immediately after it; the legacy route stays available for one
    compatibility cycle and is marked deprecated in OpenAPI. Both routes use the
    same endpoint, dependencies, validation, and authorization checks.
    """
    router_prefix = router.prefix.rstrip("/")
    full_path = f"{router_prefix}/{path.lstrip('/')}"
    tenant_marker = "/tenants/{tenant_id}"
    marker_at = full_path.find(tenant_marker)
    if marker_at < 0:
        raise ValueError("tenant admin routes require a {tenant_id} path segment")
    insert_at = marker_at + len(tenant_marker)
    canonical_full_path = f"{full_path[:insert_at]}/admin{full_path[insert_at:]}"
    canonical_path = canonical_full_path[len(router_prefix):]

    def register(endpoint: Callable[..., Any]) -> Callable[..., Any]:
        router.add_api_route(
            path, endpoint, methods=methods, deprecated=deprecated_legacy,
            name=f"{endpoint.__name__}_legacy", **options,
        )
        router.add_api_route(
            canonical_path, endpoint, methods=methods,
            name=f"{endpoint.__name__}_admin", **options,
        )
        return endpoint

    return register


def add_tenant_admin_aliases(app: Any, source_prefix: str, admin_prefix: str) -> int:
    """Clone tenant resource routes under an admin prefix without changing dependencies.

    A router may place ``/knowledge`` after ``{tenant_id}``, so the decorator above
    cannot insert ``/admin`` at the tenant boundary. Shallow-copying each APIRoute
    keeps its already-built dependency graph (including router-level authorization)
    identical while recompiling only its URL matcher and OpenAPI identity.
    """
    def included_routes(routes: list[Any], seen_routers: set[int]) -> list[APIRoute]:
        """Resolve APIRoutes inside FastAPI's lazy ``include_router`` wrappers."""
        resolved: list[APIRoute] = []
        for item in routes:
            if isinstance(item, APIRoute):
                resolved.append(item)
                continue
            nested = getattr(item, "original_router", None)
            if nested is None or id(nested) in seen_routers:
                continue
            seen_routers.add(id(nested))
            resolved.extend(included_routes(nested.routes, seen_routers))
        return resolved

    routes = included_routes(app.router.routes, set())
    existing_methods: dict[str, set[str]] = {}
    for route in routes:
        existing_methods.setdefault(route.path, set()).update(route.methods or set())
    aliases: list[APIRoute] = []
    for route in routes:
        if not (route.path == source_prefix or route.path.startswith(f"{source_prefix}/")):
            continue
        suffix = route.path[len(source_prefix):]
        alias_path = f"{admin_prefix}{suffix}"
        missing_methods = set(route.methods or set()) - existing_methods.get(alias_path, set())
        if not missing_methods:
            continue
        alias = copy(route)
        alias.path = alias_path
        alias.path_regex, alias.path_format, alias.param_convertors = compile_path(alias_path)
        alias.methods = missing_methods
        alias.name = f"{route.name}_admin_alias"
        alias.unique_id = f"{route.unique_id}_admin_alias_{'_'.join(sorted(missing_methods)).lower()}"
        if route.operation_id:
            alias.operation_id = f"{route.operation_id}_admin_alias_{'_'.join(sorted(missing_methods)).lower()}"
        aliases.append(alias)
        existing_methods.setdefault(alias_path, set()).update(missing_methods)
    app.router.routes.extend(aliases)
    return len(aliases)
