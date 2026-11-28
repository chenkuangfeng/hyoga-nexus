"""MCP domain service: service CRUD, tool discovery/cache, per-tool enablement, risk policy and stateless endpoints.

Writes open their own transaction (matching the skill service); reads run inside the caller's
transaction after membership is verified. Administrators (``tools:manage``) mutate services, tools
and policy; every active member may list. Discovered tools default to disabled (openspec 2026-11-08-mcp).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.authz.resources import deactivate_resource, register_resource
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound, PlatformError, ServiceUnavailable
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    CredentialReferenceRecord,
    McpEndpointRecord,
    McpOAuthTokenRecord,
    McpServiceRecord,
    McpServiceToolRecord,
    McpToolApprovalRecord,
)
from nexus_mcp import client as mcp_client
from nexus_mcp.client.errors import McpError, McpUnauthorized
from . import policy as risk
from .oauth import McpOAuthRequired

#: Mutating the tool catalog (services, enablement, risk) is an administrator capability.
MANAGE_PERMISSION = "tools:manage"
from .common import RESOURCE_KIND, READ_ONLY_TOOL_NAMES  # noqa: E402
#: Name charset for services (spec R1: 1-64, lowercase letters, digits, hyphen).
SERVICE_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")


class McpServiceDisabled(PlatformError):
    code = "mcp_service_disabled"
    status_code = 403


class McpUnavailable(PlatformError):
    code = "mcp_unavailable"
    status_code = 503


@dataclass(frozen=True)
class VisibleTool:
    """One enabled, authorized MCP tool resolved for a Run's model context."""

    service_id: UUID
    service_name: str
    tool_name: str
    description: str
    input_schema: dict
    output_schema: dict | None
    risk: str
    requires_approval: bool
    timeout: float


def _context(db: Session, principal: Principal, tenant_id: UUID):
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    return user


def _require_admin(db: Session, tenant_id: UUID, user_id: UUID) -> None:
    require_api_permission(db, tenant_id, user_id, MANAGE_PERMISSION)


def _service_dict(service: McpServiceRecord) -> dict[str, Any]:
    return {
        "id": str(service.id),
        "tenant_id": str(service.tenant_id),
        "name": service.name,
        "description": service.description,
        "transport": service.transport,
        "config": dict(service.config or {}),
        "enabled": service.enabled,
        "config_epoch": service.config_epoch,
        "created_by": str(service.created_by),
        "created_at": service.created_at.isoformat(),
        "updated_at": service.updated_at.isoformat(),
    }


def list_services(db: Session, principal: Principal, tenant_id: UUID) -> list[dict[str, Any]]:
    """Every service in this Tenant, newest first. Active membership required."""
    _context(db, principal, tenant_id)
    rows = db.scalars(select(McpServiceRecord).where(McpServiceRecord.tenant_id == tenant_id)
                      .order_by(McpServiceRecord.created_at.desc()))
    return [_service_dict(row) for row in rows]


def get_service(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID) -> dict[str, Any]:
    _context(db, principal, tenant_id)
    row = db.get(McpServiceRecord, service_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound("MCP service not found")
    return _service_dict(row)


def _validate_config(transport: str, config: dict) -> dict:
    """Normalize the connection config and keep only connection parameters (secret references included)."""
    try:
        return mcp_client.validate_config({"transport": transport, **config})
    except McpError as exc:
        raise InvalidConfiguration(exc.code) from None


def create_service(db: Session, principal: Principal, tenant_id: UUID, *, name: str, description: str,
                   transport: str, config: dict) -> dict[str, Any]:
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        name = (name or "").strip()
        if not SERVICE_NAME_RE.fullmatch(name):
            raise InvalidConfiguration("mcp_service_name_invalid")
        if db.scalar(select(McpServiceRecord.id).where(
                McpServiceRecord.tenant_id == tenant_id, McpServiceRecord.name == name).limit(1)):
            raise Conflict("MCP service name is already in use")
        normalized = _validate_config(transport, config)
        now = utc_now()
        row = McpServiceRecord(
            id=new_id(), tenant_id=tenant_id, name=name, description=description or "",
            transport=transport, config=normalized, enabled=True,
            config_epoch=mcp_client.new_epoch(), created_by=user.id, created_at=now, updated_at=now,
        )
        db.add(row)
        db.flush()
        register_resource(db, tenant_id=tenant_id, kind=RESOURCE_KIND, resource_id=str(row.id), version_id="")
        audit(db, tenant_id, user.id, "mcp_service.created", RESOURCE_KIND, str(row.id), {"name": name})
    return _service_dict(row)


def update_service(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID, *, name: str | None,
                   description: str | None, transport: str | None, config: dict | None,
                   enabled: bool | None) -> dict[str, Any]:
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        row = db.get(McpServiceRecord, service_id)
        if row is None or row.tenant_id != tenant_id:
            raise NotFound("MCP service not found")
        if name is not None:
            name = name.strip()
            if not SERVICE_NAME_RE.fullmatch(name):
                raise InvalidConfiguration("mcp_service_name_invalid")
            if db.scalar(select(McpServiceRecord.id).where(
                    McpServiceRecord.tenant_id == tenant_id, McpServiceRecord.name == name,
                    McpServiceRecord.id != service_id).limit(1)):
                raise Conflict("MCP service name is already in use")
            row.name = name
        if description is not None:
            row.description = description
        connection_changed = False
        if transport is not None:
            if transport != row.transport:
                connection_changed = True
            row.transport = transport
        if config is not None:
            normalized = _validate_config(row.transport, config)
            if normalized != row.config:
                connection_changed = True
            row.config = normalized
        if connection_changed:
            # A connection-parameter change must invalidate cached tools and old sessions.
            row.config_epoch = mcp_client.new_epoch()
            db.execute(delete(McpServiceToolRecord).where(McpServiceToolRecord.service_id == service_id))
        if enabled is not None:
            row.enabled = enabled
        row.updated_at = utc_now()
        audit(db, tenant_id, user.id, "mcp_service.updated", RESOURCE_KIND, str(service_id), {})
    return _service_dict(row)


def delete_service(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID) -> None:
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        row = db.get(McpServiceRecord, service_id)
        if row is None or row.tenant_id != tenant_id:
            raise NotFound("MCP service not found")
        db.delete(row)
        deactivate_resource(db, tenant_id=tenant_id, kind=RESOURCE_KIND, resource_id=str(service_id), version_id="")
        audit(db, tenant_id, user.id, "mcp_service.deleted", RESOURCE_KIND, str(service_id), {})


def resolve_config(db: Session, service: McpServiceRecord, principal_id: UUID | None = None, *,
                   force_oauth_refresh: bool = False) -> dict:
    """Resolve a service's connection config for one call, including its dynamic credential.

    Credential-reference markers in ``headers`` / ``env`` resolve from their backend; other
    backends need an injected resolver and fail closed here. For an OAuth service the token of
    `principal_id` is fetched (refreshing first when needed) and replaces any static
    ``Authorization`` header: the user-level credential outranks the service-level one.
    Resolved values are never persisted.
    """
    resolved: dict[str, object] = {}
    for section in ("headers", "env"):
        mapping = service.config.get(section)
        if not isinstance(mapping, dict):
            continue
        out: dict[str, str] = {}
        for key, value in mapping.items():
            if mcp_client.is_secret_reference(value):
                out[key] = _resolve_secret(db, service, value)
            else:
                out[key] = value
        resolved[section] = out
    result = {**service.config, **resolved}
    if service.config.get("auth_type") == "oauth":
        settings = dict(service.config.get("oauth") or {})
        secret = settings.get("client_secret")
        if mcp_client.is_secret_reference(secret):
            settings["client_secret"] = _resolve_secret(db, service, secret)
        result["oauth"] = settings
        if principal_id is None:
            raise McpOAuthRequired("MCP service requires OAuth authorization")
        from . import oauth as mcp_oauth
        value = mcp_oauth.authorization_value(db, service.tenant_id, principal_id, service,
                                              force_refresh=force_oauth_refresh)
        headers = result.get("headers")
        result["headers"] = mcp_client.replace_authorization(
            headers if isinstance(headers, dict) else {}, value)
    return result


def _resolve_secret(db: Session, service: McpServiceRecord, value: dict) -> str:
    """Resolve one credential reference after checking it belongs to this Tenant and is active."""
    reference_id = UUID(value["$credential_ref"])
    ref = db.get(CredentialReferenceRecord, reference_id)
    if ref is None or ref.tenant_id != service.tenant_id or ref.status != "active":
        raise McpUnavailable("MCP credential reference is unavailable")
    return _resolve_reference(ref)


def _resolve_reference(ref: CredentialReferenceRecord) -> str:
    if ref.backend == "environment":
        key = ref.handle
        if key.startswith("env://"):
            key = key[len("env://"):]
        value = os.environ.get(key)
        if value is None:
            raise McpUnavailable("MCP credential environment variable is not set")
        return value
    raise McpUnavailable(f"MCP credential backend {ref.backend!r} is not resolvable here")


def _discover_with_oauth_retry(db: Session, service: McpServiceRecord, principal_id: UUID,
                               resolved: dict, timeout: float
                               ) -> tuple[list[mcp_client.MCPToolSpec], dict]:
    """One discovery, then at most one forced token refresh and one retry.

    Kept separate so a failure of the retried attempt is classified by `discover_tools` like any
    other discovery failure instead of escaping the try block from inside its handler.
    """
    try:
        return asyncio.run(mcp_client.discover(resolved, timeout=timeout)), resolved
    except McpUnauthorized:
        # An OAuth server may have revoked the token the connect used even though it had not
        # locally expired yet; a non-OAuth service has no second credential to offer.
        if service.config.get("auth_type") != "oauth":
            raise
        refreshed = resolve_config(db, service, principal_id, force_oauth_refresh=True)
        return asyncio.run(mcp_client.discover(refreshed, timeout=timeout)), refreshed


def discover_tools(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID,
                   *, timeout: float = 30.0) -> dict[str, Any]:
    """Connect to the service, list its tools and refresh the cached catalog (default: all disabled).

    Token resolution and the network round trip deliberately run outside the catalog transaction:
    a refresh commits its rotated credential (see `nexus_platform.mcp.oauth.access_token`), which
    would close an enclosing ``Session.begin()`` block, and a network call inside a transaction
    would pin a database connection for the whole discovery budget.
    """
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        service = db.get(McpServiceRecord, service_id)
        if service is None or service.tenant_id != tenant_id:
            raise NotFound("MCP service not found")
        resolved = resolve_config(db, service, user.id)
    try:
        specs, resolved = _discover_with_oauth_retry(db, service, user.id, resolved, timeout)
    except McpError as exc:
        with db.begin():
            _store_discovery_error(db, service, exc.code, str(exc))
            audit(db, tenant_id, user.id, "mcp_service.discover_failed", RESOURCE_KIND, str(service_id),
                  {"error": exc.code})
        raise ServiceUnavailable(exc.code) from None
    except PlatformError:
        # OAuth re-authorization or a token-endpoint outage already carries its own status; the
        # caller (API / UI) needs that signal, not a generic connection failure.
        raise
    except Exception:  # noqa: BLE001 - discovery must not leak transport details
        with db.begin():
            _store_discovery_error(db, service, "mcp_connection_failed", "connection failed")
            audit(db, tenant_id, user.id, "mcp_service.discover_failed", RESOURCE_KIND, str(service_id),
                  {"error": "mcp_connection_failed"})
        raise ServiceUnavailable("mcp_connection_failed") from None
    with db.begin():
        fingerprint = mcp_client.fingerprint(resolved)
        now = utc_now()
        existing = {
            row.tool_name: row
            for row in db.scalars(select(McpServiceToolRecord).where(McpServiceToolRecord.service_id == service_id))
        }
        kept: set[str] = set()
        for spec in specs:
            name = mcp_client.valid_external_tool_name(spec.name)
            if name is None:
                continue
            kept.add(name)
            prior = existing.get(name)
            row = prior or McpServiceToolRecord(
                service_id=service_id, tool_name=name,
                enabled=False, fingerprint=fingerprint, config_epoch=service.config_epoch, updated_at=now,
            )
            row.description = spec.description
            row.input_schema = spec.input_schema
            row.output_schema = spec.output_schema
            row.read_only_hint = spec.read_only_hint
            row.catalog_status = "ready"
            row.catalog_error = None
            row.fingerprint = fingerprint
            row.config_epoch = service.config_epoch
            row.updated_at = now
            if prior is None:
                db.add(row)
            _observe_risk(db, tenant_id, service_id, name, spec.read_only_hint)
        for name, row in existing.items():
            if name not in kept and row.catalog_status == "ready":
                db.delete(row)
        audit(db, tenant_id, user.id, "mcp_service.discovered", RESOURCE_KIND, str(service_id),
              {"tools": sorted(kept)})
    return {"service_id": str(service_id), "tools": sorted(kept), "fingerprint": fingerprint}


def _store_discovery_error(db: Session, service: McpServiceRecord, code: str, message: str) -> None:
    now = utc_now()
    rows = list(db.scalars(select(McpServiceToolRecord).where(McpServiceToolRecord.service_id == service.id)))
    if not rows:
        rows = [McpServiceToolRecord(service_id=service.id, tool_name="", enabled=False, description="",
                                     input_schema={}, catalog_status="error", catalog_error=message,
                                     fingerprint="", config_epoch=service.config_epoch, updated_at=now)]
        db.add(rows[0])
    for row in rows:
        row.catalog_status = "error"
        row.catalog_error = message
        row.updated_at = now


def _observe_risk(db: Session, tenant_id: UUID, service_id: UUID, tool_name: str, read_only_hint: bool) -> None:
    declared = risk.declared_risk(read_only_hint)
    row = db.scalar(select(McpToolApprovalRecord).where(
        McpToolApprovalRecord.tenant_id == tenant_id, McpToolApprovalRecord.service_id == service_id,
        McpToolApprovalRecord.tool_name == tool_name))
    observed = row.observed_risk if row else None
    new_observed = risk.observe_declared(row.explicit_risk if row else None, observed, declared)
    if new_observed is not None:
        if row is None:
            row = McpToolApprovalRecord(
                id=new_id(), tenant_id=tenant_id, service_id=service_id, tool_name=tool_name,
                observed_risk=new_observed, updated_at=utc_now(),
            )
            db.add(row)
        else:
            row.observed_risk = new_observed
            row.pending_downgrade = risk.pending_downgrade(row.explicit_risk, new_observed, declared)
            row.updated_at = utc_now()


def list_tools(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID) -> list[dict[str, Any]]:
    _context(db, principal, tenant_id)
    service = db.get(McpServiceRecord, service_id)
    if service is None or service.tenant_id != tenant_id:
        raise NotFound("MCP service not found")
    rows = db.scalars(select(McpServiceToolRecord).where(McpServiceToolRecord.service_id == service_id)
                      .order_by(McpServiceToolRecord.tool_name))
    approvals = {
        (row.service_id, row.tool_name): row
        for row in db.scalars(select(McpToolApprovalRecord).where(McpToolApprovalRecord.service_id == service_id))
    }
    result = []
    for row in rows:
        if row.tool_name == "" and row.catalog_status == "error":
            continue
        approval = approvals.get((row.service_id, row.tool_name))
        declared = risk.declared_risk(row.read_only_hint)
        result.append({
            "tool_name": row.tool_name,
            "description": row.description,
            "enabled": row.enabled,
            "read_only_hint": row.read_only_hint,
            "catalog_status": row.catalog_status,
            "catalog_error": row.catalog_error,
            "explicit_risk": approval.explicit_risk if approval else None,
            "observed_risk": approval.observed_risk if approval else None,
            "effective_risk": risk.effective_risk(approval.explicit_risk if approval else None,
                                                  approval.observed_risk if approval else None, declared),
            "require_approval": approval.require_approval if approval else False,
            "pending_downgrade": risk.pending_downgrade(approval.explicit_risk if approval else None,
                                                        approval.observed_risk if approval else None, declared),
        })
    return result


def set_enabled_tools(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID,
                      names: list[str]) -> list[str]:
    """Replace the enable whitelist. Only discovered tool names are accepted."""
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        service = db.get(McpServiceRecord, service_id)
        if service is None or service.tenant_id != tenant_id:
            raise NotFound("MCP service not found")
        discovered = {row.tool_name for row in db.scalars(
            select(McpServiceToolRecord).where(McpServiceToolRecord.service_id == service_id,
                                               McpServiceToolRecord.catalog_status == "ready"))}
        cleaned: set[str] = set()
        for name in names:
            valid = mcp_client.valid_external_tool_name(name)
            if valid is None or valid not in discovered:
                raise InvalidConfiguration(f"mcp_tool_unknown:{name}")
            cleaned.add(valid)
        for row in db.scalars(select(McpServiceToolRecord).where(McpServiceToolRecord.service_id == service_id)):
            row.enabled = row.tool_name in cleaned
            row.updated_at = utc_now()
        audit(db, tenant_id, user.id, "mcp_service.tools_enabled", RESOURCE_KIND, str(service_id),
              {"tools": sorted(cleaned)})
    return sorted(cleaned)


def set_tool_policy(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID, tool_name: str, *,
                    explicit_risk: str | None, require_approval: bool, confirm_downgrade: bool = False) -> dict[str, Any]:
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        service = db.get(McpServiceRecord, service_id)
        if service is None or service.tenant_id != tenant_id:
            raise NotFound("MCP service not found")
        tool = db.scalar(select(McpServiceToolRecord).where(
            McpServiceToolRecord.service_id == service_id, McpServiceToolRecord.tool_name == tool_name))
        if tool is None or tool.catalog_status != "ready":
            raise NotFound("MCP tool not found")
        if explicit_risk is not None and explicit_risk not in risk.VALID_RISKS:
            raise InvalidConfiguration("mcp_risk_invalid")
        declared = risk.declared_risk(tool.read_only_hint)
        row = db.scalar(select(McpToolApprovalRecord).where(
            McpToolApprovalRecord.tenant_id == tenant_id, McpToolApprovalRecord.service_id == service_id,
            McpToolApprovalRecord.tool_name == tool_name))
        observed = row.observed_risk if row else None
        # Setting an explicit risk is itself the workspace confirmation; `confirm_downgrade` is
        # accepted for API compatibility and recorded in the audit metadata.
        if row is None:
            row = McpToolApprovalRecord(id=new_id(), tenant_id=tenant_id, service_id=service_id,
                                        tool_name=tool_name, updated_at=utc_now())
            db.add(row)
        row.explicit_risk = explicit_risk
        row.require_approval = bool(require_approval)
        row.pending_downgrade = risk.pending_downgrade(explicit_risk, observed, declared)
        row.updated_at = utc_now()
        audit(db, tenant_id, user.id, "mcp_service.policy_changed", RESOURCE_KIND, str(service_id),
              {"tool": tool_name, "explicit_risk": explicit_risk, "require_approval": require_approval,
               "confirm_downgrade": confirm_downgrade})
    return {"tool_name": tool_name, "effective_risk": risk.effective_risk(explicit_risk, observed, declared),
            "require_approval": require_approval, "pending_downgrade": row.pending_downgrade}


# --------------------------------------------------------------------------- endpoints

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _clean_endpoint_name(name: str) -> str:
    name = (name or "").strip()
    if not SERVICE_NAME_RE.fullmatch(name):
        raise InvalidConfiguration("mcp_endpoint_name_invalid")
    return name


def _clean_allowlist(names: list[str]) -> list[str]:
    """Normalize the tool allowlist: only known read-only tools, de-duplicated, original order kept."""
    out: list[str] = []
    for value in names or []:
        name = (value or "").strip()
        if name not in READ_ONLY_TOOL_NAMES:
            raise InvalidConfiguration(f"mcp_endpoint_tool_unknown:{name}")
        if name not in out:
            out.append(name)
    return out


def _clean_kb_ids(kb_ids: list[str]) -> list[str]:
    """Normalize the knowledge-base scope: every value must be a UUID (empty means every readable base)."""
    out: list[str] = []
    for value in kb_ids or []:
        try:
            out.append(str(UUID(str(value))))
        except (ValueError, AttributeError, TypeError):
            raise InvalidConfiguration("mcp_endpoint_kb_invalid") from None
    return list(dict.fromkeys(out))


def _endpoint_dict(endpoint: McpEndpointRecord) -> dict[str, Any]:
    return {
        "id": str(endpoint.id),
        "tenant_id": str(endpoint.tenant_id),
        "name": endpoint.name,
        "description": endpoint.description,
        "enabled": endpoint.enabled,
        "tool_allowlist": list(endpoint.tool_allowlist or []),
        "kb_ids": list(endpoint.kb_ids or []),
        "last_used_at": endpoint.last_used_at.isoformat() if endpoint.last_used_at else None,
        "created_by": str(endpoint.created_by),
        "created_at": endpoint.created_at.isoformat(),
        "updated_at": endpoint.updated_at.isoformat(),
    }


def _get_endpoint(db: Session, tenant_id: UUID, endpoint_id: UUID) -> McpEndpointRecord:
    row = db.get(McpEndpointRecord, endpoint_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound("MCP endpoint not found")
    return row


def list_endpoints(db: Session, principal: Principal, tenant_id: UUID) -> list[dict[str, Any]]:
    """Every endpoint in this Tenant, newest first. Active membership required."""
    _context(db, principal, tenant_id)
    rows = db.scalars(select(McpEndpointRecord).where(McpEndpointRecord.tenant_id == tenant_id)
                      .order_by(McpEndpointRecord.created_at.desc()))
    return [_endpoint_dict(row) for row in rows]


def get_endpoint(db: Session, principal: Principal, tenant_id: UUID, endpoint_id: UUID) -> dict[str, Any]:
    _context(db, principal, tenant_id)
    return _endpoint_dict(_get_endpoint(db, tenant_id, endpoint_id))


def create_endpoint(db: Session, principal: Principal, tenant_id: UUID, *, name: str, description: str,
                    tool_allowlist: list[str], kb_ids: list[str]) -> dict[str, Any]:
    """Create an endpoint and issue its long-lived token (plaintext appears only in this response)."""
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        name = _clean_endpoint_name(name)
        if db.scalar(select(McpEndpointRecord.id).where(
                McpEndpointRecord.tenant_id == tenant_id, McpEndpointRecord.name == name).limit(1)):
            raise Conflict("MCP endpoint name is already in use")
        allowlist = _clean_allowlist(tool_allowlist)
        kb_scope = _clean_kb_ids(kb_ids)
        token = secrets.token_urlsafe(32)
        now = utc_now()
        row = McpEndpointRecord(
            id=new_id(), tenant_id=tenant_id, name=name, description=description or "", enabled=True,
            tool_allowlist=allowlist, kb_ids=kb_scope, token_hash=_hash_token(token),
            created_by=user.id, created_at=now, updated_at=now,
        )
        db.add(row)
        db.flush()
        audit(db, tenant_id, user.id, "mcp_endpoint.created", "mcp_endpoint", str(row.id),
              {"name": name, "tools": allowlist, "kb_ids": kb_scope})
    result = _endpoint_dict(row)
    result["token"] = token
    return result


def update_endpoint(db: Session, principal: Principal, tenant_id: UUID, endpoint_id: UUID, *, name: str | None,
                    description: str | None, tool_allowlist: list[str] | None, kb_ids: list[str] | None,
                    enabled: bool | None) -> dict[str, Any]:
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        row = _get_endpoint(db, tenant_id, endpoint_id)
        if name is not None:
            name = _clean_endpoint_name(name)
            if db.scalar(select(McpEndpointRecord.id).where(
                    McpEndpointRecord.tenant_id == tenant_id, McpEndpointRecord.name == name,
                    McpEndpointRecord.id != endpoint_id).limit(1)):
                raise Conflict("MCP endpoint name is already in use")
            row.name = name
        if description is not None:
            row.description = description
        if tool_allowlist is not None:
            row.tool_allowlist = _clean_allowlist(tool_allowlist)
        if kb_ids is not None:
            row.kb_ids = _clean_kb_ids(kb_ids)
        if enabled is not None:
            row.enabled = enabled
        row.updated_at = utc_now()
        audit(db, tenant_id, user.id, "mcp_endpoint.updated", "mcp_endpoint", str(endpoint_id), {})
    return _endpoint_dict(row)


def delete_endpoint(db: Session, principal: Principal, tenant_id: UUID, endpoint_id: UUID) -> None:
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        row = _get_endpoint(db, tenant_id, endpoint_id)
        db.delete(row)
        audit(db, tenant_id, user.id, "mcp_endpoint.deleted", "mcp_endpoint", str(endpoint_id), {})


def rotate_endpoint_token(db: Session, principal: Principal, tenant_id: UUID, endpoint_id: UUID) -> dict[str, Any]:
    """Issue a new token; the old one stops working. Plaintext appears only in this response."""
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        row = _get_endpoint(db, tenant_id, endpoint_id)
        token = secrets.token_urlsafe(32)
        row.token_hash = _hash_token(token)
        row.updated_at = utc_now()
        audit(db, tenant_id, user.id, "mcp_endpoint.token_rotated", "mcp_endpoint", str(endpoint_id), {})
    result = _endpoint_dict(row)
    result["token"] = token
    return result


def revoke_endpoint_token(db: Session, principal: Principal, tenant_id: UUID, endpoint_id: UUID) -> dict[str, Any]:
    """Clear the token hash so no token authenticates until the next rotate."""
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        row = _get_endpoint(db, tenant_id, endpoint_id)
        row.token_hash = ""
        row.updated_at = utc_now()
        audit(db, tenant_id, user.id, "mcp_endpoint.token_revoked", "mcp_endpoint", str(endpoint_id), {})
    return _endpoint_dict(row)


def resolve_endpoint_token(db: Session, token: str) -> McpEndpointRecord:
    """Resolve a long-lived endpoint token to a live, enabled endpoint.

    Fails closed with a single ``Forbidden("unauthorized")`` for every failure (unknown token, revoked,
    disabled) so the protocol never reveals whether a resource exists.
    """
    row = db.scalar(select(McpEndpointRecord).where(
        McpEndpointRecord.token_hash == _hash_token(token)).limit(1))
    if row is None or not row.enabled:
        raise Forbidden("unauthorized")
    return row


def _service_ids(service_ids) -> set[UUID]:
    """Coerce bound service resource ids (strings) to UUIDs, dropping malformed values."""
    ids: set[UUID] = set()
    for value in service_ids or []:
        try:
            ids.add(UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            continue
    return ids


def context_version(tool: VisibleTool) -> str:
    """Fingerprint the enabled schema and effective risk used by a frozen model catalog.

    MCP catalogs have no immutable published version: a changed risk/schema must invalidate the
    frozen advertisement rather than silently applying the previous approval requirements.
    """
    from nexus_core.runtime.context import context_digest
    return context_digest({'name': tool.tool_name, 'description': tool.description,
        'schema': tool.input_schema, 'risk': tool.risk, 'approval': tool.requires_approval})


def visible_tools(db: Session, tenant_id: UUID, service_ids) -> list[VisibleTool]:
    """Tools of services bound to the Run's agent, enabled at both service and tool level, with policy.

    Binding is resolved by the caller (Run preparation); this reads live service/tool/policy state and
    never trusts a cached snapshot. A policy read failure is fail-close (write + approval).
    """
    ids = _service_ids(service_ids)
    if not ids:
        return []
    services = list(db.scalars(select(McpServiceRecord).where(
        McpServiceRecord.id.in_(ids), McpServiceRecord.tenant_id == tenant_id,
        McpServiceRecord.enabled.is_(True))))
    admitted_ids = [service.id for service in services]
    catalog = {}
    for tool in db.scalars(select(McpServiceToolRecord).where(
            McpServiceToolRecord.service_id.in_(admitted_ids), McpServiceToolRecord.enabled.is_(True),
            McpServiceToolRecord.catalog_status == 'ready')):
        catalog.setdefault(tool.service_id, []).append(tool)
    policies = {(p.service_id, p.tool_name): p for p in db.scalars(select(McpToolApprovalRecord).where(
        McpToolApprovalRecord.tenant_id == tenant_id, McpToolApprovalRecord.service_id.in_(admitted_ids)))}
    visible: list[VisibleTool] = []
    for service in services:
        if service.tenant_id != tenant_id or not service.enabled:
            continue
        for tool in catalog.get(service.id, []):
            approval = policies.get((service.id, tool.tool_name))
            declared = risk.declared_risk(tool.read_only_hint)
            effective, requires = risk.risk_action(
                approval.explicit_risk if approval else None,
                approval.observed_risk if approval else None,
                declared,
                approval.require_approval if approval else False,
            )
            timeout = float(service.config.get("timeout", 30)) if isinstance(service.config, dict) else 30.0
            visible.append(VisibleTool(service_id=service.id, service_name=service.name, tool_name=tool.tool_name,
                                       description=tool.description, input_schema=tool.input_schema,
                                       output_schema=tool.output_schema, risk=effective,
                                       requires_approval=requires, timeout=timeout))
    return sorted(visible, key=lambda t: (str(t.service_id), t.tool_name))


def resolve_call(db: Session, tenant_id: UUID, service_id: UUID, tool_name: str, *,
                 principal_id: UUID | None = None,
                 force_oauth_refresh: bool = False) -> tuple[dict, dict | None, float]:
    """Re-validate a service and tool right before a call, returning the resolved connection config.

    This is the execution-time recheck (WeKnora ``checkEnabled``): the service and tool must still be
    enabled, the tool catalog must still be ready, and credential references must resolve. Fails closed on
    any mismatch so a definition advertised earlier never bypasses a later disable or revocation.
    """
    service = db.get(McpServiceRecord, service_id)
    if service is None or service.tenant_id != tenant_id or not service.enabled:
        raise McpServiceDisabled("MCP service is disabled or not available")
    tool = db.scalar(select(McpServiceToolRecord).where(
        McpServiceToolRecord.service_id == service_id, McpServiceToolRecord.tool_name == tool_name,
        McpServiceToolRecord.enabled.is_(True), McpServiceToolRecord.catalog_status == "ready"))
    if tool is None:
        raise McpServiceDisabled("MCP tool is disabled or not available")
    resolved = resolve_config(db, service, principal_id, force_oauth_refresh=force_oauth_refresh)
    timeout = float(service.config.get("timeout", 30)) if isinstance(service.config, dict) else 30.0
    return resolved, tool.output_schema, timeout
