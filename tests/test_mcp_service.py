"""MCP domain service: CRUD, discovery/enablement, risk policy and stateless endpoints (openspec 2026-11-08-mcp)."""
import pytest

from nexus_core.platform import Principal, new_id, utc_now
from uuid import UUID
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound, ServiceUnavailable
from nexus_platform.identity.service import resolve_user
from nexus_platform.mcp import service as mcp
from nexus_platform.persistence.models import CredentialReferenceRecord, McpServiceRecord
from test_platform import database  # noqa: F401
from sqlalchemy import update

PRINCIPAL = Principal(id="alice", issuer="test")


def _tenant(factory):
    with factory() as db:
        from nexus_platform.tenants.service import create_tenant
        tenant = create_tenant(db, PRINCIPAL, "MCP")
    return tenant


def _create(factory, tenant, **kw):
    with factory() as db:
        return mcp.create_service(db, PRINCIPAL, tenant.id, name="github", description="GitHub",
                                  transport="streamable_http", config={"url": "https://mcp.example/api"}, **kw)


def spec():
    from nexus_mcp.client import MCPToolSpec
    return MCPToolSpec(name="get_repo", description="read a repo",
                       input_schema={"type": "object", "properties": {}}, read_only_hint=False, output_schema=None)


def _patch_discover(monkeypatch, specs=None, error=None):
    async def fake_discover(config, timeout=30):
        if error is not None:
            raise error
        return specs if specs is not None else [spec()]

    monkeypatch.setattr("nexus_mcp.client.discover", fake_discover)


def test_service_name_is_validated_and_unique(database):
    tenant = _tenant(database)
    with database() as db:
        with pytest.raises(InvalidConfiguration):
            mcp.create_service(db, PRINCIPAL, tenant.id, name="Bad Name!", description="", transport="streamable_http",
                               config={"url": "https://x"})
    _create(database, tenant)
    with database() as db:
        with pytest.raises(Conflict):
            mcp.create_service(db, PRINCIPAL, tenant.id, name="github", description="", transport="streamable_http",
                               config={"url": "https://x"})


def test_service_crud_and_connection_change_invalidates_tools(database, monkeypatch):
    tenant = _tenant(database)
    created = _create(database, tenant)
    service_id = UUID(created["id"])
    assert created["enabled"] is True and created["transport"] == "streamable_http"

    _patch_discover(monkeypatch)
    with database() as db:
        result = mcp.discover_tools(db, PRINCIPAL, tenant.id, service_id)
        assert result["tools"] == ["get_repo"]
    with database() as db:
        tools = mcp.list_tools(db, PRINCIPAL, tenant.id, service_id)
        assert tools[0]["tool_name"] == "get_repo"
        assert tools[0]["enabled"] is False
        assert tools[0]["catalog_status"] == "ready"
        assert tools[0]["effective_risk"] == "write"

    with database() as db:
        mcp.update_service(db, PRINCIPAL, tenant.id, service_id, name=None, description=None,
                           transport=None, config={"url": "https://mcp.example/api/v2"}, enabled=None)
    with database() as db:
        assert mcp.list_tools(db, PRINCIPAL, tenant.id, service_id) == []

    with database() as db:
        mcp.delete_service(db, PRINCIPAL, tenant.id, service_id)
    with database() as db:
        with pytest.raises(NotFound):
            mcp.get_service(db, PRINCIPAL, tenant.id, service_id)


def test_discovery_failure_marks_status_error(database, monkeypatch):
    tenant = _tenant(database)
    created = _create(database, tenant)
    from nexus_mcp.client.errors import McpConnectionError
    _patch_discover(monkeypatch, error=McpConnectionError("down", code="mcp_connection_failed"))
    with database() as db:
        with pytest.raises(ServiceUnavailable):
            mcp.discover_tools(db, PRINCIPAL, tenant.id, UUID(created["id"]))


def test_set_enabled_tools_accepts_only_discovered_names(database, monkeypatch):
    tenant = _tenant(database)
    created = _create(database, tenant)
    _patch_discover(monkeypatch)
    with database() as db:
        mcp.discover_tools(db, PRINCIPAL, tenant.id, UUID(created["id"]))
    with database() as db:
        assert mcp.set_enabled_tools(db, PRINCIPAL, tenant.id, UUID(created["id"]), ["get_repo"]) == ["get_repo"]
    with database() as db:
        assert mcp.list_tools(db, PRINCIPAL, tenant.id, UUID(created["id"]))[0]["enabled"] is True
    with database() as db:
        with pytest.raises(InvalidConfiguration):
            mcp.set_enabled_tools(db, PRINCIPAL, tenant.id, UUID(created["id"]), ["nope"])


def test_risk_policy_explicit_wins_and_approval_flag(database, monkeypatch):
    tenant = _tenant(database)
    created = _create(database, tenant)
    _patch_discover(monkeypatch)
    sid = UUID(created["id"])
    with database() as db:
        mcp.discover_tools(db, PRINCIPAL, tenant.id, sid)
    with database() as db:
        policy = mcp.set_tool_policy(db, PRINCIPAL, tenant.id, sid, "get_repo",
                                     explicit_risk="destructive", require_approval=True)
        assert policy["effective_risk"] == "destructive" and policy["require_approval"] is True
    with database() as db:
        policy = mcp.set_tool_policy(db, PRINCIPAL, tenant.id, sid, "get_repo",
                                     explicit_risk="read", require_approval=False)
        assert policy["effective_risk"] == "read"


def test_service_declared_downgrade_stays_at_observed(database, monkeypatch):
    tenant = _tenant(database)
    created = _create(database, tenant)
    sid = UUID(created["id"])

    async def write_discover(config, timeout=30):
        return [spec()]

    async def read_discover(config, timeout=30):
        from nexus_mcp.client import MCPToolSpec
        return [MCPToolSpec(name="get_repo", description="read a repo",
                            input_schema={"type": "object", "properties": {}}, read_only_hint=True)]

    monkeypatch.setattr("nexus_mcp.client.discover", write_discover)
    with database() as db:
        mcp.discover_tools(db, PRINCIPAL, tenant.id, sid)
    monkeypatch.setattr("nexus_mcp.client.discover", read_discover)
    with database() as db:
        mcp.discover_tools(db, PRINCIPAL, tenant.id, sid)
    with database() as db:
        tool = mcp.list_tools(db, PRINCIPAL, tenant.id, sid)[0]
        assert tool["observed_risk"] == "write"
        assert tool["effective_risk"] == "write"
        assert tool["pending_downgrade"] is True


def test_environment_credential_reference_resolution(database, monkeypatch):
    tenant = _tenant(database)
    with database() as db:
        resolve_user(db, PRINCIPAL)
        ref = CredentialReferenceRecord(id=new_id(), tenant_id=tenant.id, backend="environment",
                                        handle="env://MCP_TOKEN", scope={}, status="active", created_at=utc_now())
        db.add(ref)
        db.commit()
        ref_id = ref.id
    created = _create(database, tenant)
    with database() as db:
        db.execute(update(McpServiceRecord)
                   .where(McpServiceRecord.id == UUID(created["id"]))
                   .values(config={"transport": "streamable_http", "url": "https://mcp.example/api",
                                   "headers": {"Authorization": {"$credential_ref": str(ref_id)}}}))
        db.commit()
    monkeypatch.setenv("MCP_TOKEN", "tok")
    _patch_discover(monkeypatch)
    with database() as db:
        mcp.discover_tools(db, PRINCIPAL, tenant.id, UUID(created["id"]))
    monkeypatch.delenv("MCP_TOKEN")
    with database() as db:
        with pytest.raises(mcp.McpUnavailable):
            mcp.discover_tools(db, PRINCIPAL, tenant.id, UUID(created["id"]))


def test_endpoint_token_lifecycle(database):
    tenant = _tenant(database)
    with database() as db:
        created = mcp.create_endpoint(db, PRINCIPAL, tenant.id, name="readonly",
                                      description="read face", tool_allowlist=["search_knowledge"], kb_ids=[])
    token = created["token"]
    endpoint_id = UUID(created["id"])
    with database() as db:
        resolved = mcp.resolve_endpoint_token(db, token)
        assert resolved.id == endpoint_id
        assert resolved.token_hash != token  # only the hash is stored

    with database() as db:
        rotated = mcp.rotate_endpoint_token(db, PRINCIPAL, tenant.id, endpoint_id)
    assert rotated["token"] != token
    # the old token is dead, the new one authenticates
    with database() as db:
        with pytest.raises(Forbidden):
            mcp.resolve_endpoint_token(db, token)
        assert mcp.resolve_endpoint_token(db, rotated["token"]).id == endpoint_id

    with database() as db:
        mcp.revoke_endpoint_token(db, PRINCIPAL, tenant.id, endpoint_id)
    with database() as db:
        with pytest.raises(Forbidden):
            mcp.resolve_endpoint_token(db, rotated["token"])


def test_endpoint_crud_validates_allowlist_and_names(database):
    tenant = _tenant(database)
    with database() as db:
        with pytest.raises(InvalidConfiguration):
            mcp.create_endpoint(db, PRINCIPAL, tenant.id, name="readonly", description="",
                                tool_allowlist=["delete_all_the_things"], kb_ids=[])
    with database() as db:
        created = mcp.create_endpoint(db, PRINCIPAL, tenant.id, name="readonly", description="read face",
                                      tool_allowlist=["search_knowledge", "web_search"], kb_ids=[])
    endpoint_id = UUID(created["id"])
    with database() as db:
        with pytest.raises(Conflict):
            mcp.create_endpoint(db, PRINCIPAL, tenant.id, name="readonly", description="",
                                tool_allowlist=["search_knowledge"], kb_ids=[])
        updated = mcp.update_endpoint(db, PRINCIPAL, tenant.id, endpoint_id, name=None, description="narrower",
                                      tool_allowlist=["web_search"], kb_ids=None, enabled=None)
        assert updated["tool_allowlist"] == ["web_search"]
        mcp.delete_endpoint(db, PRINCIPAL, tenant.id, endpoint_id)
        with pytest.raises(NotFound):
            mcp.get_endpoint(db, PRINCIPAL, tenant.id, endpoint_id)
