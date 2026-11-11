"""`skill_manage`, `skill_save`, `skill_rollback` through the real Run store (openspec 2026-11-07-skill-evolution, S4 4.3)."""
import asyncio

import pytest
from sqlalchemy import select

from nexus_platform.persistence.models import AuditRecord, SkillRecord
from nexus_platform.runs.preparation import prepare_execution
from nexus_platform.runs.service import claim_next, create_run
from nexus_platform.runs.store import DurableRuntimeStore
from nexus_platform.sessions.service import create_session
from nexus_tools.builtins.registration import builtins
from nexus_tools import policy
from test_native_runtime import FakeModel  # noqa: F401
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _agent, _tenant, _version_for
from types import SimpleNamespace

MD = '---\nname: my-notes\ndescription: Keeps my notes tidy\ntools: []\n---\n# Steps\nWrite short notes.\nSame line\nSame line\n'
TOOLS = ('load_skill', 'read_skill_file', 'skill_manage', 'skill_save', 'skill_rollback')


@pytest.fixture
def run(database):
    """A prepared Run of an agent that can write skills but binds none."""
    import test_skills_platform as base
    from nexus_platform.authz.resources import register_resource
    tenant, model_version = _tenant(database)
    with database() as db:
        for name in ('skill_manage', 'skill_save', 'skill_rollback'):
            register_resource(db, tenant_id=tenant.id, kind='tool', resource_id=name, version_id='v1')
        db.commit()
    agent_id = _agent(database, tenant, model_version, [], tools=TOOLS)
    agent_version_id = _version_for(database, tenant, agent_id)
    with database() as db:
        session = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='S')
        created, _ = create_run(db, PRINCIPAL, tenant.id, session.id, message='Write a skill', idempotency_key='sk-1')
    with database() as db:
        task = claim_next(db, 'skill-worker')
    context = prepare_execution(database, task, 'skill-worker')
    assert context is not None
    store = DurableRuntimeStore(database, context, 'skill-worker', task)
    return SimpleNamespace(tenant=tenant, store=store, context=context, services=store)


def _call(run, tool_name, **arguments):
    tool = builtins().get(tool_name, 'v1')
    return asyncio.run(tool.handler(arguments, SimpleNamespace(services=run.store)))


def test_write_save_and_load_in_one_conversation(database, run):
    created = _call(run, 'skill_manage', action='create', skill_md=MD, files={'refs/a.md': 'one'})
    assert 'Draft my-notes updated' in created.data and 'Nothing is live' in created.data
    with pytest.raises(Exception):  # not live until saved: a draft cannot be loaded as a skill
        asyncio.run(run.store.load_skill('my-notes'))
    saved = _call(run, 'skill_save', name='my-notes')
    assert 'Saved my-notes as version 1' in saved.data and 'live now' in saved.data and saved.error_code is None
    body = asyncio.run(run.store.load_skill('my-notes'))
    assert 'Write short notes' in body  # usable in the same conversation, no new agent version
    assert 'one' in asyncio.run(run.store.read_skill_file('my-notes', 'refs/a.md'))
    with database() as db:
        actions = [a.action for a in db.scalars(select(AuditRecord))]
        assert 'skill.draft' in actions and 'skill.saved' in actions
        detail = next(a for a in db.scalars(select(AuditRecord)) if a.action == 'skill.draft').metadata_json
        assert detail == {'action': 'create', 'skill': 'my-notes'}  # no content in the audit log


def test_guard_errors_come_back_as_codes_the_model_can_act_on(database, run):
    _call(run, 'skill_manage', action='create', skill_md=MD)
    blind = _call(run, 'skill_manage', action='patch', name='nope', old_string='x', new_string='y')
    assert blind.error_code == 'skill_draft_unread'
    _call(run, 'skill_manage', action='view', name='my-notes')
    ambiguous = _call(run, 'skill_manage', action='patch', name='my-notes', old_string='Same line', new_string='x')
    assert ambiguous.error_code == 'skill_patch_ambiguous'
    fixed = _call(run, 'skill_manage', action='patch', name='my-notes', old_string='Same line', new_string='x', replace_all=True)
    assert fixed.error_code is None
    outside = _call(run, 'skill_manage', action='write_file', name='my-notes', path='etc/passwd', content='x')
    assert outside.error_code == 'skill_draft_path_not_allowed'
    unknown = _call(run, 'skill_manage', action='view', name='missing')
    assert unknown.error_code == 'skill_draft_not_found'


def test_a_dangerous_skill_is_refused_with_the_finding(database, run, monkeypatch):
    monkeypatch.setattr('nexus_platform.skills.service.sandbox_can_build', lambda db, profile: True)
    _call(run, 'skill_manage', action='create', skill_md=MD, files={'scripts/clean.sh': 'rm -rf ~\n'})
    refused = _call(run, 'skill_save', name='my-notes')
    assert refused.error_code == 'skill_scan_refused' and 'scripts/clean.sh' in refused.data
    with database() as db:
        assert db.scalar(select(SkillRecord)) is None


def test_rollback_and_a_second_version(database, run):
    _call(run, 'skill_manage', action='create', skill_md=MD)
    _call(run, 'skill_save', name='my-notes')
    _call(run, 'skill_manage', action='view', name='my-notes')
    _call(run, 'skill_manage', action='patch', name='my-notes', old_string='Write short notes', new_string='Write brief notes')
    assert 'version 2' in _call(run, 'skill_save', name='my-notes').data
    assert 'brief notes' in asyncio.run(run.store.load_skill('my-notes'))
    assert 'now uses version 1' in _call(run, 'skill_rollback', name='my-notes', version=1).data
    assert 'short notes' in asyncio.run(run.store.load_skill('my-notes'))
    assert _call(run, 'skill_rollback', name='my-notes', version=9).error_code == 'skill_version_not_found'


def test_saving_asks_for_confirmation_every_time_and_cannot_be_remembered():
    definitions = {name: builtins().get(name, 'v1').definition for name in ('skill_manage', 'skill_save', 'skill_rollback')}
    save = definitions['skill_save']
    assert save.risk == 'destructive' and save.requires_approval and save.group == 'skills'
    assert policy.decide(save.risk, 'standard', save.requires_approval) == 'ask'
    assert policy.decide(save.risk, 'read_only', save.requires_approval) == 'deny'
    from nexus_platform.runs.approvals import rememberable
    assert rememberable(SimpleNamespace(reason='policy', risk='destructive')) is False  # no "allow for this session"
    assert policy.decide(definitions['skill_manage'].risk, 'standard', False) == 'allow'
    assert 'name' in definitions['skill_manage'].description and 'under 160 bytes' in definitions['skill_manage'].description
