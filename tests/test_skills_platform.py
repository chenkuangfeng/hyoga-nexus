"""Platform rules for skills: publish, bindings, run-time reads, session index and publish checks.

Proposal 2026-11-04-skill-scripts, tasks 3.2, 4.2–4.4, 6.1–6.5. Uses the SQLite fixture from test_platform.
"""
import pytest

from nexus_core.platform import Principal
from nexus_platform.agents.service import create_agent, publish_agent
from nexus_platform.authz.resources import register_resource
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound
from nexus_platform.models.service import create_model_profile
from nexus_platform.persistence.models import PlatformResourceRecord, SessionSkillSnapshotRecord
from nexus_platform.skills.service import publish, read_for_run, session_index
from nexus_platform.tenants.service import create_tenant
from test_platform import database  # noqa: F401  (pytest fixture)

from sqlalchemy import select

SKILL = ('---\nname: report-writer\ndescription: Writes weekly reports\ntools: ["read_memory"]\n---\n'
         '# Steps\nSearch memory, then write <b>the report</b>.\n')
PRINCIPAL = Principal(id='alice', issuer='test')


def _tenant(factory):
    with factory() as db:
        tenant = create_tenant(db, PRINCIPAL, 'Skills')
        _, model_version = create_model_profile(db, PRINCIPAL, tenant.id, name='M', provider='openai',
                                                model_name='test', options={'base_url': 'https://model.example/v1'})
        for name in ('load_skill', 'read_skill_file', 'read_memory'):
            register_resource(db, tenant_id=tenant.id, kind='tool', resource_id=name, version_id='v1')
        db.commit()
    return tenant, model_version


def _publish(factory, tenant, text=SKILL, files=None):
    with factory() as db:
        return publish(db, PRINCIPAL, tenant.id, text, files or {})


def _agent(factory, tenant, model_version, skills, tools=('load_skill', 'read_skill_file', 'read_memory')):
    bindings = [{'kind': 'skill', 'resource_id': s['skill'], 'resource_version_id': s['version_id'],
                 'source_tenant_id': str(tenant.id), 'config': {}} for s in skills]
    bindings += [{'kind': 'tool', 'resource_id': t, 'resource_version_id': 'v1',
                  'source_tenant_id': str(tenant.id), 'config': {}} for t in tools]
    with factory() as db:
        agent = create_agent(db, PRINCIPAL, tenant.id, name='Writer', description='', runtime_type='native',
                             instructions='', model_profile_version_id=model_version.id, budgets={},
                             bindings=bindings)
        return agent.id


def test_publish_creates_version_one_and_registers_it_as_a_resource(database):
    tenant, _ = _tenant(database)
    result = _publish(database, tenant, files={'refs/style.md': 'Use short sentences.'})
    assert result['version'] == 1 and result['skill'] == 'report-writer'
    with database() as db:
        row = db.scalar(select(PlatformResourceRecord).where(PlatformResourceRecord.kind == 'skill',
                                                             PlatformResourceRecord.version_id == result['version_id']))
        assert row is not None and row.active


def test_identical_republish_is_refused_and_changed_content_creates_version_two(database):
    tenant, _ = _tenant(database)
    _publish(database, tenant)
    with pytest.raises(Conflict, match='skill_version_unchanged'):
        _publish(database, tenant)
    assert _publish(database, tenant, text=SKILL.replace('weekly', 'daily'))['version'] == 2


def test_publish_rejects_undeclared_tools_and_missing_scripts(database):
    tenant, _ = _tenant(database)
    with pytest.raises(InvalidConfiguration, match='skill_tool_unknown:made_up'):
        _publish(database, tenant, text=SKILL.replace('["read_memory"]', '["made_up"]'))
    script_skill = ('---\nname: runner\ndescription: d\nscripts: [{"name": "go", "path": "scripts/go.py", '
                    '"interpreter": "python3"}]\n---\nBody\n')
    with pytest.raises(InvalidConfiguration, match='skill_script_missing:go'):
        _publish(database, tenant, text=script_skill)


def test_publish_reports_static_hints_without_blocking(database):
    tenant, _ = _tenant(database)
    text = ('---\nname: netcheck\ndescription: d\nscripts: [{"name": "go", "path": "scripts/go.py", '
            '"interpreter": "python3"}]\n---\nBody\n')
    result = _publish(database, tenant, text=text, files={'scripts/go.py': 'import requests\n'})
    assert result['scan_hints'] == [{'category': 'network', 'path': 'scripts/go.py', 'line': 1}]


def test_agent_publish_requires_skill_readers_and_declared_tools(database):
    tenant, model_version = _tenant(database)
    published = _publish(database, tenant)
    with database() as db:
        agent = create_agent(db, PRINCIPAL, tenant.id, name='No readers', description='', runtime_type='native',
                             instructions='', model_profile_version_id=model_version.id, budgets={},
                             bindings=[{'kind': 'skill', 'resource_id': 'report-writer',
                                        'resource_version_id': published['version_id'],
                                        'source_tenant_id': str(tenant.id), 'config': {}}])
        with pytest.raises(InvalidConfiguration, match='skill_dependency_missing:load_skill'):
            publish_agent(db, PRINCIPAL, tenant.id, agent.id)
    agent_id = _agent(database, tenant, model_version, [published], tools=('load_skill', 'read_skill_file'))
    with database() as db:
        with pytest.raises(InvalidConfiguration, match='skill_dependency_missing:read_memory'):
            publish_agent(db, PRINCIPAL, tenant.id, agent_id)


def _version_for(factory, tenant, agent_id):
    from nexus_platform.persistence.models import AgentVersionRecord
    with factory() as db:
        agent_version = publish_agent(db, PRINCIPAL, tenant.id, agent_id)
        return agent_version.id


def test_reads_are_limited_to_bound_skills_and_their_files(database):
    tenant, model_version = _tenant(database)
    published = _publish(database, tenant, files={'refs/style.md': 'Short.'})
    other = _publish(database, tenant, text=SKILL.replace('report-writer', 'unbound-skill'))
    agent_id = _agent(database, tenant, model_version, [published])
    agent_version_id = _version_for(database, tenant, agent_id)
    with database() as db:
        body = read_for_run(db, tenant.id, agent_version_id, 'report-writer')
        assert '&lt;b&gt;the report&lt;/b&gt;' in body and '<b>' not in body
        assert 'grants no permissions' in body
        assert 'Short.' in read_for_run(db, tenant.id, agent_version_id, 'report-writer', 'refs/style.md')
        with pytest.raises(NotFound):
            read_for_run(db, tenant.id, agent_version_id, 'unbound-skill')
        for escaping in ('../report-writer', 'refs/missing.md', '/etc/passwd'):
            with pytest.raises(NotFound):
                read_for_run(db, tenant.id, agent_version_id, 'report-writer', escaping)


def test_revoked_skill_is_refused_at_read_time(database):
    tenant, model_version = _tenant(database)
    published = _publish(database, tenant)
    agent_version_id = _version_for(database, tenant, _agent(database, tenant, model_version, [published]))
    with database() as db:
        row = db.scalar(select(PlatformResourceRecord).where(PlatformResourceRecord.kind == 'skill'))
        row.active = False
        db.commit()
    with database() as db:
        with pytest.raises(NotFound):
            read_for_run(db, tenant.id, agent_version_id, 'report-writer')


def test_session_index_is_frozen_for_the_session(database):
    tenant, model_version = _tenant(database)
    first = _publish(database, tenant)
    agent_version_id = _version_for(database, tenant, _agent(database, tenant, model_version, [first]))
    from nexus_platform.sessions.service import create_session
    with database() as db:
        session = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='S')
        session_id = session.id
    with database() as db:
        text = session_index(db, tenant.id, session_id, agent_version_id)
        db.commit()
        assert text == 'report-writer | Writes weekly reports'
    with database() as db:
        assert db.get(SessionSkillSnapshotRecord, session_id).index_text == text
        # Changing the stored text shows the next Run reads the snapshot, not the live bindings.
        db.get(SessionSkillSnapshotRecord, session_id).index_text = 'frozen-by-test'
        db.commit()
    with database() as db:
        assert session_index(db, tenant.id, session_id, agent_version_id) == 'frozen-by-test'
