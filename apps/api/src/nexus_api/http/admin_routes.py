"""Helpers for dual publishing tenant administration routes during API migration."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


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
