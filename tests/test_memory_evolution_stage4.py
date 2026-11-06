"""Memory evolution stage 4: past-conversation search (openspec 2026-11-06-memory-evolution, D1).

The tools only read the caller's other sessions in the Run's space, hide messages of Runs whose history
is no longer visible, page with bounds, and follow the memory switches.
"""
import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from nexus_core.platform import Principal, TenantRole, utc_now
from nexus_platform.identity.service import resolve_user
from nexus_platform.tenants.service import add_member
from nexus_core.runtime import RuntimeFault
from nexus_memory import switches as switch_rules
from nexus_platform.memory import conversations
from nexus_platform.persistence.models import AuditRecord, MessageRecord, RunRecord, SessionRecord
from nexus_platform.runs.store import DurableRuntimeStore
from nexus_tools.builtins.catalog import builtin_catalog

from test_memory_switches import _member, _prepare
from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)

TOOLS = sorted(switch_rules.MEMORY_TOOL_NAMES)


def _old_session(factory, run, rows, *, owner=None, tenant=None, title='旧会话'):
    """A finished earlier session of the run's owner (or another owner) with the given messages."""
    with factory() as db, db.begin():
        current = db.get(SessionRecord, run.session_id)
        session = SessionRecord(id=uuid4(), tenant_id=tenant or run.tenant_id, owner_user_id=owner or run.principal_id,
                                agent_version_id=current.agent_version_id, runtime_type=current.runtime_type,
                                title=title, status='active', created_at=utc_now(), updated_at=utc_now())
        db.add(session)
        db.flush()
        for sequence, (role, content) in enumerate(rows, start=1):
            db.add(MessageRecord(id=uuid4(), session_id=session.id, run_id=run.id, sequence=sequence, role=role,
                                 content=content, runtime_metadata={},
                                 created_at=utc_now() - timedelta(days=3) + timedelta(seconds=sequence)))
        return session.id


def test_search_and_read_cover_only_the_owners_other_sessions(database):  # noqa: F811
    _, tenant, session, run, _ = stack(database, TOOLS)
    old = _old_session(database, run, [('user', '我们决定发布窗口定在周四晚上'), ('assistant', '好的，周四晚上发布'),
                                      ('tool', '周四晚上 tool output'), ('user', '另外回滚负责人是小王')])
    with database() as db, db.begin():  # the current session mentions it too, and must not be returned
        db.add(MessageRecord(id=uuid4(), session_id=session.id, run_id=run.id, sequence=99, role='user',
                             content='周四晚上发布吗', runtime_metadata={}, created_at=utc_now()))
    context, task = _prepare(database)
    store = DurableRuntimeStore(database, context, 'memory-worker', task)
    found = asyncio.run(store.search_conversations('周四晚上', 5))
    lines = [line for line in found.split('\n') if line.startswith('[')]
    assert len(lines) == 2 and all(str(old) in line for line in lines)
    assert '旧会话' in lines[0] and 'tool output' not in found
    page = asyncio.run(store.read_conversation(str(old), 2, 1, 1))
    assert page.startswith(f'<past_conversation session="{old}">') and '#1 user: 我们决定发布窗口' in page
    assert '#3' not in page and '#4 user: 另外回滚负责人是小王' in page  # tool rows are skipped
    assert asyncio.run(store.read_conversation(str(session.id), 1, 1, 1)) == 'Conversation not found.'
    assert asyncio.run(store.read_conversation('not-a-uuid', 1, 1, 1)) == 'Conversation not found.'
    with database() as db:
        assert db.scalar(select(AuditRecord).where(AuditRecord.action == 'conversation.search')) is not None


def test_other_peoples_sessions_and_revoked_runs_are_never_returned(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database, TOOLS)
    member = Principal(id='conversation-colleague', issuer='test')
    with database() as db:
        add_member(db, principal, tenant.id, member, TenantRole.ADMIN)
    with database() as db, db.begin():
        stranger = resolve_user(db, member).id
    _old_session(database, run, [('user', '机密发布计划')], owner=stranger)
    revoked = _old_session(database, run, [('user', '撤权后的发布计划')])
    with database() as db:
        hits = conversations.search(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
                                    current_session_id=session.id, query='发布计划')
    assert [h['session_id'] for h in hits] == [str(revoked)]
    # Revoke: the Run's snapshot now names a resource that is no longer granted.
    with database() as db, db.begin():
        row = db.get(RunRecord, run.id)
        row.config_snapshot = {**row.config_snapshot, 'resources': [
            {'kind': 'tool', 'resource_id': 'gone', 'source_tenant_id': str(run.tenant_id)}]}
    with database() as db:
        assert conversations.search(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
                                    current_session_id=session.id, query='发布计划') == []


def test_paging_is_bounded():
    assert conversations.MAX_SIDE == 10 and conversations.PAGE_CHARS == 8000


def test_conversation_tools_follow_the_memory_switches_and_appear_in_the_memory_group(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database, TOOLS)
    context, task = _prepare(database)
    assert {'search_conversations', 'read_conversation'} <= {name for name, _, _ in context.bindings}
    store = DurableRuntimeStore(database, context, 'memory-worker', task)
    _member(database, principal, tenant.id, False)
    with pytest.raises(RuntimeFault) as refused:
        asyncio.run(store.authorize('search_conversations', 'v1'))
    assert refused.value.code == 'memory_disabled'
    groups = {entry.name: entry.group for entry in builtin_catalog()}
    assert groups['search_conversations'] == groups['read_conversation'] == 'memory'
