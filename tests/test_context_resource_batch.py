"""Bulk catalog authorization preserves scalar precedence and request-time revocation."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, select

from nexus_core.platform import SYSTEM_TENANT_ID, utc_now
from nexus_core.runtime import ModelChunk, ToolResult
from nexus_platform.authz.resource_batch import ResourceAuthorizationBatch
from nexus_platform.authz.resources import authorize_resource, register_resource, revoke_resource_grant
from nexus_platform.errors import PlatformError
from nexus_platform.persistence.models import PlatformResourceRecord, RunRecord, McpServiceRecord
from nexus_platform.system import ensure_system_resources, disable_builtin
from nexus_platform.mcp import service as mcp
from nexus_mcp import gateway as mcp_gateway
from nexus_worker.__main__ import run_once
from nexus_tools.builtins import builtins

from test_platform import database  # noqa: F401
from test_native_runtime import stack, FakeModel, call, run_row
from test_mcp_service import _patch_discover, spec


def test_resource_batch_matches_local_builtin_shared_and_revoked_scalar_access(database):
    principal, tenant, _, run, grants = stack(database, ['echo'], shared=True)
    with database() as db:
        ensure_system_resources(db)
    source = grants[0].source_tenant_id
    requests = [('tool', 'echo', source, 'v1'), ('tool', 'echo', None, 'v1'),
                ('tool', 'echo', tenant.id, 'v1'), ('tool', 'echo', source, 'missing'),
                ('tool', 'read_memory', SYSTEM_TENANT_ID, 'v1'), ('tool', 'read_memory', None, 'v1')]
    def verify():
        with database() as db:
            batch = ResourceAuthorizationBatch(db, tenant.id, requests)
            for kind, name, origin, version in requests:
                for permission in ('read', 'use'):
                    try:
                        expected = authorize_resource(db, tenant.id, kind, name, source_tenant_id=origin,
                                                      resource_version_id=version, permission=permission).id
                    except PlatformError:
                        with pytest.raises(PlatformError):
                            batch.authorize(kind, name, origin, version, permission)
                    else:
                        assert batch.authorize(kind, name, origin, version, permission).id == expected
    verify()
    with database() as db:
        disable_builtin(db, principal, tenant.id, 'tool', 'read_memory')
    with database() as db:
        revoke_resource_grant(db, principal, grants[0].id)
    verify()
    # A local registration wins over a disabled same-name builtin when source is local/unspecified.
    with database() as db, db.begin():
        register_resource(db, tenant_id=tenant.id, kind='tool', resource_id='read_memory', version_id='v1')
    verify()


@pytest.mark.parametrize('size', [100, 1000])
def test_catalog_fact_queries_scale_by_batch_instead_of_per_tool(database, size):
    _, tenant, _, _, _ = stack(database)
    names = [f'scale_tool_{i}' for i in range(size)]
    with database() as db, db.begin():
        db.execute(insert(PlatformResourceRecord), [dict(id=uuid4(), tenant_id=tenant.id, kind='tool',
            resource_id=name, version_id='v1', active=True, created_at=utc_now()) for name in names])
    statements = []
    def count(conn, cursor, statement, *_):
        statements.append(statement)
    engine = database.kw['bind']
    event.listen(engine, 'before_cursor_execute', count)
    try:
        with database() as db:
            requests = [('tool', name, tenant.id, 'v1') for name in names]
            batch = ResourceAuthorizationBatch(db, tenant.id, requests)
            before = len(statements)
            assert all(batch.authorize(*request).resource_id == request[1] for request in requests)
            assert len(statements) == before
            assert before == 3 * ((size + 299) // 300)
    finally:
        event.remove(engine, 'before_cursor_execute', count)


@pytest.mark.parametrize('change_policy', [False, True])
def test_mcp_worker_uses_run_owned_catalog_and_rechecks_policy(database, monkeypatch, change_policy):
    from nexus_mcp.client import MCPToolSpec
    principal, tenant, _, run, _ = stack(database, budgets={'behavior': {'tool_groups_enabled': {'mcp': True}}})
    with database() as db:
        created = mcp.create_service(db, principal, tenant.id, name='ctx', description='',
            transport='streamable_http', config={'url': 'https://mcp.example/api'})
    sid = UUID(created['id'])
    _patch_discover(monkeypatch, [MCPToolSpec(name='get_repo', description='read',
        input_schema={'type': 'object', 'properties': {}}, read_only_hint=True)])
    with database() as db:
        mcp.discover_tools(db, principal, tenant.id, sid)
    with database() as db:
        mcp.set_enabled_tools(db, principal, tenant.id, sid, ['get_repo'])
    with database() as db, db.begin():
        row = db.get(RunRecord, run.id)
        row.config_snapshot = {**row.config_snapshot, 'mcp_service_ids': [str(sid)]}
    async def invoke(*_, **__):
        if change_policy:
            with database() as db:
                mcp.set_tool_policy(db, principal, tenant.id, sid, 'get_repo',
                                    explicit_risk='destructive', require_approval=True)
        return ToolResult('mcp-result')
    monkeypatch.setattr('nexus_mcp.client.call', invoke)
    name = mcp_gateway.registered_name(str(sid), 'ctx', 'get_repo')
    model = FakeModel([[call(name)], [ModelChunk('text', text='done')]])
    run_once(database, 'w', model_factory=lambda _: model)
    if change_policy:
        assert run_row(database, run.id).error_code == 'run_authorization_denied'
        assert len(model.requests) == 1
        assert builtins().get(name, 'v1') is None
        return
    assert run_row(database, run.id).status == 'completed'
    assert name in {d.name for d in model.requests[0].tools}
    assert builtins().get(name, 'v1') is None
    assert any(m.role == 'tool' and 'mcp-result' in m.content for m in model.requests[1].messages)


def test_plugin_resource_dependency_rechecks_cross_space_grant(database):
    from nexus_core.runtime.context import ContextDependency
    from nexus_platform.runs.context_access import sources_allowed
    principal, tenant, _, run, grants = stack(database, ['echo'], shared=True)
    with database() as db:
        resource = db.scalar(select(PlatformResourceRecord).where(
            PlatformResourceRecord.tenant_id == grants[0].source_tenant_id,
            PlatformResourceRecord.resource_id == 'echo'))
        dependency = ContextDependency('resource', str(resource.id), resource.version_id)
        assert sources_allowed(db, db.get(RunRecord, run.id), (dependency,))
    with database() as db:
        revoke_resource_grant(db, principal, grants[0].id)
    with database() as db:
        assert not sources_allowed(db, db.get(RunRecord, run.id), (dependency,))
