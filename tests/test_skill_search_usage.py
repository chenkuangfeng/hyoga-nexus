"""`skill_search` and skill usage records (openspec 2026-11-07-skill-evolution, 6.4 / 6.2)."""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from nexus_platform.authz.resources import register_resource
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import SkillRecord, SkillUsageRecord
from nexus_platform.runs.preparation import prepare_execution
from nexus_platform.runs.service import claim_next, create_run
from nexus_platform.runs.store import DurableRuntimeStore
from nexus_platform.sessions.service import create_session
from nexus_platform.skills import private
from nexus_platform.skills.service import list_skills, publish, search_usable, session_index, usage_totals
from nexus_tools.builtins.registration import builtins
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _agent, _tenant, _version_for

def _md(name, description, body='Steps.'):
    return f'---\nname: {name}\ndescription: {description}\ntools: []\n---\n{body}\n'


@pytest.fixture
def run(database):
    tenant, model_version = _tenant(database)
    with database() as db:
        register_resource(db, tenant_id=tenant.id, kind='tool', resource_id='skill_search', version_id='v1')
        db.commit()
    with database() as db:
        a = publish(db, PRINCIPAL, tenant.id, _md('report-writer', 'Writes weekly reports', 'Collect the numbers, then summarize.'), {})
        b = publish(db, PRINCIPAL, tenant.id, _md('data-cleaner', 'Cleans csv files'), {})
        c = publish(db, PRINCIPAL, tenant.id, _md('zhoubao', '整理每周工作周报，帮助写周报'), {})
    agent_id = _agent(database, tenant, model_version, [a, b, c], tools=('load_skill', 'read_skill_file', 'skill_search'))
    agent_version_id = _version_for(database, tenant, agent_id)
    with database() as db:
        session = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='S')
        create_run(db, PRINCIPAL, tenant.id, session.id, message='hi', idempotency_key='ss-1')
    with database() as db:
        task = claim_next(db, 'w')
    ctx = prepare_execution(database, task, 'w')
    store = DurableRuntimeStore(database, ctx, 'w', task)
    with database() as db:
        with db.begin():
            user = context(db, PRINCIPAL, tenant.id)[0].id
    return SimpleNamespace(tenant=tenant, store=store, agent_version_id=agent_version_id, user=user)


def _search(run, query, limit=None):
    arguments = {'query': query, **({'limit': limit} if limit else {})}
    return asyncio.run(builtins().get('skill_search', 'v1').handler(arguments, SimpleNamespace(services=run.store)))


def test_search_ranks_name_over_description_over_body(database, run):
    with database() as db:
        found = search_usable(db, run.tenant.id, run.agent_version_id, run.user, 'weekly report')
    assert [name for name, _ in found][0] == 'report-writer'
    with database() as db:
        assert [n for n, _ in search_usable(db, run.tenant.id, run.agent_version_id, run.user, 'summarize')] == ['report-writer']  # body only
        assert [n for n, _ in search_usable(db, run.tenant.id, run.agent_version_id, run.user, 'csv')] == ['data-cleaner']  # description
        assert search_usable(db, run.tenant.id, run.agent_version_id, run.user, 'astronomy') == []


def test_search_understands_chinese_without_spaces(database, run):
    with database() as db:
        assert [n for n, _ in search_usable(db, run.tenant.id, run.agent_version_id, run.user, '写周报')] == ['zhoubao']


def test_search_finds_the_users_private_skills_and_nobody_elses(database, run):
    with database() as db, db.begin():
        private.create(db, run.tenant.id, run.user, _md('trip-planner', 'Plans business trips'))
        private.save(db, run.tenant.id, run.user, 'trip-planner')
    with database() as db:
        assert [n for n, _ in search_usable(db, run.tenant.id, run.agent_version_id, run.user, 'trips')] == ['trip-planner']
        assert search_usable(db, run.tenant.id, run.agent_version_id, None, 'trips') == []


def test_the_tool_reports_hits_and_misses_and_is_read_only(database, run):
    assert 'report-writer | Writes weekly reports' in _search(run, 'report').data
    assert 'Load one with load_skill' in _search(run, 'report').data
    assert 'No skill you can use matches' in _search(run, 'astronomy').data
    definition = builtins().get('skill_search', 'v1').definition
    assert definition.read_only and definition.group == 'skills' and definition.risk == 'read'


def test_a_truncated_index_points_to_the_search_tool(database, run, monkeypatch):
    monkeypatch.setattr('nexus_platform.skills.service.INDEX_LIMIT', 60)
    with database() as db:
        from nexus_platform.sessions.service import create_session
        sid = create_session(db, PRINCIPAL, run.tenant.id, agent_version_id=run.agent_version_id, title='T').id
        text = session_index(db, run.tenant.id, sid, run.agent_version_id, run.user)
        assert text.endswith('(more skills exist; find them with skill_search)')
        assert all(len(line) <= 90 for line in text.splitlines())


def test_loading_counts_and_running_a_script_only_refreshes_the_time(database, run):
    asyncio.run(run.store.load_skill('report-writer'))
    asyncio.run(run.store.load_skill('report-writer'))
    with database() as db:
        skill = db.scalar(select(SkillRecord).where(SkillRecord.name == 'report-writer'))
        totals = usage_totals(db, [skill.id])[skill.id]
        assert totals['use_count'] == 2 and totals['last_used_at']
        listed = {row['name']: row for row in list_skills(db, PRINCIPAL, run.tenant.id)}
        assert listed['report-writer']['use_count'] == 2 and listed['report-writer']['last_used_at']
        assert listed['data-cleaner']['use_count'] == 0 and listed['data-cleaner']['last_used_at'] is None


def test_private_skills_show_the_owners_own_numbers_and_loading_works_after_a_failed_note(database, run, monkeypatch):
    with database() as db, db.begin():
        private.create(db, run.tenant.id, run.user, _md('trip-planner', 'Plans business trips'))
        private.save(db, run.tenant.id, run.user, 'trip-planner')
    asyncio.run(run.store.load_skill('trip-planner'))
    with database() as db, db.begin():
        mine = private.listing(db, run.tenant.id, run.user)['skills'][0]
        assert mine['use_count'] == 1 and mine['last_used_at']
        # library lists never include private skills or their usage
        assert 'trip-planner' not in {row['name'] for row in list_skills(db, PRINCIPAL, run.tenant.id)}
    # A broken usage note must never stop a skill from loading.
    import sqlalchemy.exc
    def boom(*a, **k):
        raise sqlalchemy.exc.OperationalError('x', {}, Exception('db'))
    monkeypatch.setattr('nexus_platform.skills.service.SkillUsageRecord', boom)
    assert 'Steps.' in asyncio.run(run.store.load_skill('trip-planner'))
