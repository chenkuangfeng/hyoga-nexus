"""MCP domain service: service CRUD, tool discovery/cache, per-tool enablement, risk policy and run tokens.

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
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, RunStatus, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.authz.resources import deactivate_resource, register_resource
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound, PlatformError, ServiceUnavailable
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    CredentialReferenceRecord,
    McpOAuthTokenRecord,
    McpRunTokenRecord,
    McpServiceRecord,
    McpServiceToolRecord,
    McpToolApprovalRecord,
    RunRecord,
)
from nexus_mcp import client as mcp_client
from nexus_mcp.client.errors import McpError
from . import policy as risk

#: Mutating the tool catalog (services, enablement, risk) is an administrator capability.
MANAGE_PERMISSION = "tools:manage"
#: Resource kind used in ``platform_resources`` / ``agent_resource_bindings`` for MCP services.
RESOURCE_KIND = "mcp_service"
#: Name charset for services (spec R1: 1-64, lowercase letters, digits, hyphen).
SERVICE_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
#: Default run-token lifetime.
RUN_TOKEN_TTL = timedelta(hours=12)


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


def resolve_config(db: Session, service: McpServiceRecord) -> dict:
    """Resolve credential-reference markers in a service's config into plain strings.

    ``environment`` references resolve from the process environment; other backends need an injected
    resolver and fail closed here with a stable code. Resolved values are never persisted.
    """
    resolved: dict[str, object] = {}
    for section in ("headers", "env"):
        mapping = service.config.get(section)
        if not isinstance(mapping, dict):
            continue
        out: dict[str, str] = {}
        for key, value in mapping.items():
            if mcp_client.is_secret_reference(value):
                reference_id = UUID(value["$credential_ref"])
                ref = db.get(CredentialReferenceRecord, reference_id)
                if ref is None or str(ref.tenant_id) != str(service.tenant_id) or ref.status != "active":
                    raise McpUnavailable("MCP credential reference is unavailable")
                out[key] = _resolve_reference(ref)
            else:
                out[key] = value
        resolved[section] = out
    return {**service.config, **resolved}


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


def discover_tools(db: Session, principal: Principal, tenant_id: UUID, service_id: UUID,
                   *, timeout: float = 30.0) -> dict[str, Any]:
    """Connect to the service, list its tools and refresh the cached catalog (default: all disabled)."""
    with db.begin():
        user = _context(db, principal, tenant_id)
        _require_admin(db, tenant_id, user.id)
        service = db.get(McpServiceRecord, service_id)
        if service is None or service.tenant_id != tenant_id:
            raise NotFound("MCP service not found")
        resolved = resolve_config(db, service)
        try:
            specs = asyncio.run(mcp_client.discover(resolved, timeout=timeout))
        except McpError as exc:
            _store_discovery_error(db, service, exc.code, str(exc))
            audit(db, tenant_id, user.id, "mcp_service.discover_failed", RESOURCE_KIND, str(service_id),
                  {"error": exc.code})
            raise ServiceUnavailable(exc.code) from None
        except Exception as exc:  # noqa: BLE001 - discovery must not leak transport details
            _store_discovery_error(db, service, "mcp_connection_failed", "connection failed")
            audit(db, tenant_id, user.id, "mcp_service.discover_failed", RESOURCE_KIND, str(service_id),
                  {"error": "mcp_connection_failed"})
            raise ServiceUnavailable("mcp_connection_failed") from None
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


# --------------------------------------------------------------------------- run tokens

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def aware(value: datetime) -> datetime:
    """Treat stored timestamps as UTC: SQLite returns naive datetimes for timezone-aware columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def issue_run_token(db: Session, run_id: UUID, *, ttl: timedelta = RUN_TOKEN_TTL) -> str:
    """Issue a short-lived, single-Run token. The plaintext appears only in this return value."""
    run = db.get(RunRecord, run_id)
    if run is None:
        raise NotFound("Run not found")
    token = secrets.token_urlsafe(32)
    db.add(McpRunTokenRecord(token_hash=_hash_token(token), run_id=run_id, tenant_id=run.tenant_id,
                             expires_at=utc_now() + ttl, created_at=utc_now()))
    db.flush()
    return token


def resolve_run_token(db: Session, token: str) -> RunRecord:
    """Resolve a run token to a live, non-terminal Run; fail closed on expiry, revocation or bad status."""
    row = db.get(McpRunTokenRecord, _hash_token(token))
    now = utc_now()
    if row is None or row.revoked_at is not None or aware(row.expires_at) <= now:
        raise Forbidden("unauthorized")
    run = db.get(RunRecord, row.run_id)
    if run is None or str(run.tenant_id) != str(row.tenant_id) or RunStatus(run.status).terminal:
        raise Forbidden("unauthorized")
    return run


def revoke_run_token(db: Session, run_id: UUID) -> None:
    """Revoke every token issued for a Run (Run end / cancel)."""
    for row in db.scalars(select(McpRunTokenRecord).where(McpRunTokenRecord.run_id == run_id)):
        if row.revoked_at is None:
            row.revoked_at = utc_now()


def _service_ids(service_ids) -> set[UUID]:
    """Coerce bound service resource ids (strings) to UUIDs, dropping malformed values."""
    ids: set[UUID] = set()
    for value in service_ids or []:
        try:
            ids.add(UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            continue
    return ids


def visible_tools(db: Session, tenant_id: UUID, service_ids) -> list[VisibleTool]:
    """Tools of services bound to the Run's agent, enabled at both service and tool level, with policy.

    Binding is resolved by the caller (Run preparation); this reads live service/tool/policy state and
    never trusts a cached snapshot. A policy read failure is fail-close (write + approval).
    """
    ids = _service_ids(service_ids)
    if not ids:
        return []
    services = db.scalars(select(McpServiceRecord).where(McpServiceRecord.id.in_(ids)))
    visible: list[VisibleTool] = []
    for service in services:
        if service.tenant_id != tenant_id or not service.enabled:
            continue
        tool_rows = db.scalars(select(McpServiceToolRecord).where(
            McpServiceToolRecord.service_id == service.id,
            McpServiceToolRecord.enabled.is_(True), McpServiceToolRecord.catalog_status == "ready"))
        for tool in tool_rows:
            approval = db.scalar(select(McpToolApprovalRecord).where(
                McpToolApprovalRecord.tenant_id == tenant_id, McpToolApprovalRecord.service_id == service.id,
                McpToolApprovalRecord.tool_name == tool.tool_name))
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
    return visible


def resolve_call(db: Session, tenant_id: UUID, service_id: UUID, tool_name: str) -> tuple[dict, dict | None, float]:
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
    resolved = resolve_config(db, service)
    timeout = float(service.config.get("timeout", 30)) if isinstance(service.config, dict) else 30.0
    return resolved, tool.output_schema, timeout
