"""`exec_skill` through the Run store and the real worker (openspec 2026-11-07-skill-evolution, S2).

The sandbox is the `local` profile (development mode with `allow_local`), which runs real processes; the worker,
gateway, approval records and Run store are the real ones. These tests replace those of the retired
`run_skill_script`: the same gates, events and audit, with scripts that need no declaration.
"""
import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from nexus_core.platform import SYSTEM_USER_ID
from nexus_core.runtime import ModelChunk
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.persistence.models import AuditRecord, RunEventRecord, SkillVersionRecord
from nexus_platform.runs.approvals import list_pending, resolve
from nexus_platform.runs.preparation import prepare_execution
from nexus_platform.runs.service import claim_next, create_run, list_events
from nexus_platform.runs.store import DurableRuntimeStore
from nexus_platform.skills.service import import_builtin_as
from nexus_platform.sessions.service import create_session
from nexus_sandbox.manager import SandboxManager
from nexus_sandbox.settings import load_settings
from nexus_worker.__main__ import run_once
from test_native_runtime import FakeModel, call, run_row
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _agent, _publish, _tenant, _version_for

SKILL = '---\nname: greeter\ndescription: Greets\ntools: []\n---\n# Run the scripts under $NEXUS_SKILL_DIR/scripts\n'
FILES = {
    'scripts/go.py': 'import json, sys\nprint("hello", json.load(sys.stdin)["text"])\n',
    'scripts/argv.py': 'import json, sys\nprint(json.dumps(sys.argv[1:]))\n',
    'scripts/where.sh': 'echo "$NEXUS_SKILL_DIR"; echo "$NEXUS_SKILL_OUTPUT_DIR"; cat "$NEXUS_SKILL_DIR/SKILL.md" | head -c 20\n',
    'scripts/handoff_write.py': 'open("handoff.txt", "w").write("from step one")\n',
    'scripts/handoff_read.py': 'print(open("handoff.txt").read())\n',
    'scripts/missing_module.py': 'import a_module_that_does_not_exist\n',
    'scripts/slow.py': 'import time\ntime.sleep(30)\n',
    'scripts/perl.pl': '#!/usr/bin/perl\nprint 1;\n',
    'refs/notes.md': 'notes',
}
TOOLS = ('load_skill', 'read_skill_file', 'exec_skill')


@pytest.fixture
def gate(monkeypatch, tmp_path):
    """A development deployment: the sandbox on, one `local` profile, short skill timeouts."""
    path = tmp_path / 'nexus.toml'
    path.write_text(f'[sandbox]\nenabled = true\nallow_local = true\nworkspace_root = {json.dumps(str(tmp_path / "sbx"))}\n'
                    '[sandbox.profiles.local]\ntype = "local"\nskill_timeout_seconds = 5\nskill_timeout_max_seconds = 6\n',
                    encoding='utf-8')
    monkeypatch.setattr('nexus_core.deployment.config_path', lambda: path)
    monkeypatch.setattr('nexus_platform.configuration.auth_settings', lambda *a, **k: SimpleNamespace(mode='development'))
    import nexus_worker.sandbox_runtime as runtime
    runtime._config.cache_clear(), runtime._managers.clear()
    yield path
    runtime._config.cache_clear(), runtime._managers.clear()


def _run_context(database, budgets=None, tools=TOOLS, skill=SKILL, files=FILES):
    tenant, model_version = _tenant(database)
    published = _publish(database, tenant, text=skill, files=files)
    agent_id = _agent(database, tenant, model_version, [published], tools=tools, budgets=budgets)
    agent_version_id = _version_for(database, tenant, agent_id)
    with database() as db:
        session = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='S')
        run, _ = create_run(db, PRINCIPAL, tenant.id, session.id, message='Greet', idempotency_key='g-1')
        run_id = run.id
    with database() as db:
        task = claim_next(db, 'script-worker')
    context = prepare_execution(database, task, 'script-worker')
    return tenant.id, run_id, context, task


def _exec(database, gate, script, args=None, stdin=None, timeout=0, **context_options):
    tenant_id, run_id, context, task = _run_context(database, **context_options)
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    session = SandboxManager(load_settings(gate)).session(str(context.tenant_id), str(context.session_id))
    run = asyncio.run(store.exec_skill('greeter', script, args, stdin, timeout, session))
    return tenant_id, run_id, run


def test_the_tool_is_offered_and_the_script_runs_with_input_events_and_an_audit_record(database, gate):
    tenant_id, run_id, context, task = _run_context(database)
    assert context is not None and 'exec_skill' in [name for name, _, _ in context.bindings]
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    session = SandboxManager(load_settings(gate)).session(str(context.tenant_id), str(context.session_id))
    run = asyncio.run(store.exec_skill('greeter', 'scripts/go.py', [], '{"text": "world"}', 0, session))
    assert run.refused == '' and run.result.exit_code == 0 and run.result.stdout.strip() == 'hello world'
    with database() as db:
        kinds = [event.event_type for event in list_events(db, PRINCIPAL, tenant_id, run_id, 0)]
        record = db.scalar(select(AuditRecord).where(AuditRecord.action == 'skill.script'))
    assert 'skill.script.started' in kinds and 'skill.script.completed' in kinds
    detail = record.metadata_json
    assert detail['script'] == 'scripts/go.py' and len(detail['script_hash']) == 64 and detail['exit_code'] == 0


def test_arguments_reach_the_script_untouched_by_the_shell(database, gate):
    nasty = ['plain', 'two words', ';', '$(echo pwned)', '`echo pwned`', '*', '"quoted"', "it's", '--flag=a b', '']
    _, _, run = _exec(database, gate, 'scripts/argv.py', nasty)
    assert json.loads(run.result.stdout) == nasty


def test_the_script_finds_its_directory_and_the_output_directory(database, gate):
    _, _, run = _exec(database, gate, 'scripts/where.sh')
    skill_dir, output_dir, head = run.result.stdout.splitlines()[:3]
    assert '/skills/greeter@' in skill_dir and output_dir.endswith('/outputs') and head.startswith('---')


def test_scripts_of_one_skill_hand_data_over_through_the_workspace(database, gate):
    tenant_id, run_id, context, task = _run_context(database)
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    session = SandboxManager(load_settings(gate)).session(str(context.tenant_id), str(context.session_id))
    first = asyncio.run(store.exec_skill('greeter', 'scripts/handoff_write.py', [], None, 0, session))
    second = asyncio.run(store.exec_skill('greeter', 'scripts/handoff_read.py', [], None, 0, session))
    assert first.result.exit_code == 0 and second.result.stdout.strip() == 'from step one'


@pytest.mark.parametrize('script', ['scripts/nope.py', '../scripts/go.py', '/etc/passwd', 'SKILL.md', 'refs/notes.md', 'scripts/perl.pl'])
def test_a_missing_script_a_path_outside_the_skill_or_an_unlisted_interpreter_is_refused(database, gate, script):
    tenant_id, run_id, context, task = _run_context(database)
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    session = SandboxManager(load_settings(gate)).session(str(context.tenant_id), str(context.session_id))
    with pytest.raises(NotFound):
        asyncio.run(store.exec_skill('greeter', script, [], None, 0, session))


def test_an_unbound_skill_is_unavailable(database, gate):
    tenant_id, run_id, context, task = _run_context(database)
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    session = SandboxManager(load_settings(gate)).session(str(context.tenant_id), str(context.session_id))
    with pytest.raises(NotFound):
        asyncio.run(store.exec_skill('other-skill', 'scripts/go.py', [], None, 0, session))


def test_bad_arguments_are_refused_without_running(database, gate):
    _, _, run = _exec(database, gate, 'scripts/argv.py', [1, 2])
    assert run.refused == 'skill_script_args_invalid' and run.result is None


def test_a_missing_module_comes_with_a_direction_that_is_not_pip_install(database, gate):
    _, _, run = _exec(database, gate, 'scripts/missing_module.py')
    assert run.result.exit_code != 0 and 'ModuleNotFoundError' in run.result.stderr
    assert 'administrator' in run.hint and 'pip install' not in run.hint


def test_a_script_that_outlasts_the_skill_timeout_is_killed(database, gate):
    _, _, run = _exec(database, gate, 'scripts/slow.py', timeout=1)
    assert run.result.timed_out is True and run.result.exit_code is None


def test_the_requested_timeout_is_capped_by_the_profiles_skill_ceiling(database, gate):
    _, _, run = _exec(database, gate, 'scripts/slow.py', timeout=3600)
    assert run.result.timed_out is True and run.result.duration_ms < 8000  # the profile allows at most 6 seconds


# ------------------------------------------------------------------ the skill text names its directory

PLACEHOLDER_SKILL = ('---\nname: greeter\ndescription: Greets\ntools: []\n---\n'
                     'Run python3 ${NEXUS_SKILL_DIR}/scripts/go.py and keep $NEXUS_SKILL_DIR as it is.\n')


def test_load_skill_names_the_real_directory_and_the_script_is_there(database, gate):
    tenant_id, run_id, context, task = _run_context(database, skill=PLACEHOLDER_SKILL)
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    session = SandboxManager(load_settings(gate)).session(str(context.tenant_id), str(context.session_id))
    text = asyncio.run(store.load_skill('greeter', session))
    assert '${NEXUS_SKILL_DIR}' not in text and '$NEXUS_SKILL_DIR as it is' in text  # only the braced form is replaced
    path = text.split('python3 ', 1)[1].split(' ', 1)[0]
    assert path.endswith('/scripts/go.py') and '/skills/greeter@' in path
    assert open(path, encoding='utf-8').read().startswith('import json')  # projected, so the path is real


def test_without_a_sandbox_the_placeholder_is_left_alone_and_loading_still_works(database, gate):
    tenant_id, run_id, context, task = _run_context(database, skill=PLACEHOLDER_SKILL)
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    text = asyncio.run(store.load_skill('greeter', None))
    assert '${NEXUS_SKILL_DIR}/scripts/go.py' in text


def test_a_resource_file_gets_the_same_treatment(database, gate):
    files = {**FILES, 'refs/howto.md': 'Use ${NEXUS_SKILL_DIR}/scripts/argv.py'}
    tenant_id, run_id, context, task = _run_context(database, files=files)
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    session = SandboxManager(load_settings(gate)).session(str(context.tenant_id), str(context.session_id))
    text = asyncio.run(store.read_skill_file('greeter', 'refs/howto.md', session))
    assert '${NEXUS_SKILL_DIR}' not in text and '/skills/greeter@' in text


# ------------------------------------------------------------------ where a skill may run

def _builtin_host_skill(database, tmp_path):
    """A builtin skill whose author wants the host (`execution: local`), published into the system space."""
    folder = tmp_path / 'builtin' / 'hostly'
    (folder / 'scripts').mkdir(parents=True)
    (folder / 'SKILL.md').write_text('---\nname: hostly\ndescription: Needs the host\nexecution: local\n---\nBody\n', encoding='utf-8')
    (folder / 'scripts' / 'hi.sh').write_text('echo hi from the host\n', encoding='utf-8')
    with database() as db:
        assert import_builtin_as(db, SYSTEM_USER_ID, tmp_path / 'builtin')[0]['status'] == 'published'
    with database() as db:
        version = db.scalar(select(SkillVersionRecord).where(SkillVersionRecord.execution == 'local'))
        return {'skill': 'hostly', 'version_id': str(version.id)}


def _host_run(database, gate, tmp_path):
    tenant, model_version = _tenant(database)
    published = _builtin_host_skill(database, tmp_path)
    agent_version_id = _version_for(database, tenant, _agent(database, tenant, model_version, [published], tools=TOOLS))
    with database() as db:
        session = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='S')
        create_run(db, PRINCIPAL, tenant.id, session.id, message='Run', idempotency_key='host-1')
    with database() as db:
        task = claim_next(db, 'script-worker')
    context = prepare_execution(database, task, 'script-worker')
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    session = SandboxManager(load_settings(gate)).session(str(context.tenant_id), str(context.session_id))
    return asyncio.run(store.exec_skill('hostly', 'scripts/hi.sh', [], None, 0, session))


def test_a_builtin_skill_that_wants_the_host_is_refused_until_the_deployment_allows_it(database, gate, tmp_path):
    refused = _host_run(database, gate, tmp_path)
    assert refused.refused == 'local_not_allowed' and refused.result is None  # no silent move to somewhere else


def test_a_builtin_skill_that_wants_the_host_runs_once_the_deployment_allows_it(database, gate, tmp_path):
    gate.write_text(gate.read_text(encoding='utf-8').replace('allow_local = true\n', 'allow_local = true\nallow_local_scripts = true\n'),
                    encoding='utf-8')
    run = _host_run(database, gate, tmp_path)
    assert run.refused == '' and run.result.stdout.strip() == 'hi from the host'


# ------------------------------------------------------------------ availability

def test_without_a_usable_sandbox_the_tool_is_not_offered_and_the_call_is_refused(database, tmp_path, monkeypatch):
    monkeypatch.setattr('nexus_core.deployment.config_path', lambda: tmp_path / 'absent.toml')  # sandbox off
    tenant_id, run_id, context, task = _run_context(database)
    assert 'exec_skill' not in [name for name, _, _ in context.bindings]
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    with pytest.raises(NotFound):
        asyncio.run(store.exec_skill('greeter', 'scripts/go.py', [], None, 0, None))


def test_outside_development_mode_a_local_profile_does_not_offer_it(database, gate, monkeypatch):
    monkeypatch.setattr('nexus_platform.configuration.auth_settings', lambda *a, **k: SimpleNamespace(mode='production'))
    _, _, context, _ = _run_context(database)
    assert 'exec_skill' not in [name for name, _, _ in context.bindings]


def test_the_agent_setting_off_hides_the_tool(database, gate):
    _, _, context, _ = _run_context(database, budgets={'behavior': {'skill_scripts': False}})
    assert 'exec_skill' not in [name for name, _, _ in context.bindings]


def test_a_retired_tool_name_in_a_saved_version_is_ignored(database, gate):
    _, _, context, _ = _run_context(database, tools=TOOLS,
                                    budgets={'behavior': {'enabled_tools': ['run_skill_script']}})
    assert context is not None and 'run_skill_script' not in [name for name, _, _ in context.bindings]


# ------------------------------------------------------------------ through the real worker

CALL = json.dumps({'name': 'greeter', 'script': 'scripts/go.py', 'stdin': '{"text": "approved"}'})


def _worker_run(database, key, budgets=None):
    tenant, model_version = _tenant(database)
    published = _publish(database, tenant, text=SKILL, files=FILES)
    agent_version_id = _version_for(database, tenant, _agent(database, tenant, model_version, [published], tools=TOOLS, budgets=budgets))
    with database() as db:
        session = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='Approve')
        run, _ = create_run(db, PRINCIPAL, tenant.id, session.id, message='Greet', idempotency_key=key)
        return tenant.id, run.id


def _kinds(database, run_id):
    with database() as db:
        return [row.event_type for row in db.scalars(select(RunEventRecord).where(RunEventRecord.run_id == run_id)
                                                     .order_by(RunEventRecord.sequence))]


def _text(text):
    return ModelChunk('text', text=text)


def test_in_the_standard_access_level_the_script_runs_without_asking(database, gate):
    tenant_id, run_id = _worker_run(database, 'std-1')
    model = FakeModel([[call('exec_skill', CALL)], [_text('done')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    assert run_row(database, run_id).status == 'completed'
    assert _kinds(database, run_id).count('skill.script.started') == 1
    tool_messages = [m.content for m in model.requests[1].messages if m.role == 'tool']
    assert any('hello approved' in text and 'greeter v1 scripts/go.py' in text for text in tool_messages)


def test_in_the_strict_access_level_approval_waits_and_an_approved_script_runs_once(database, gate):
    tenant_id, run_id = _worker_run(database, 'strict-1', budgets={'behavior': {'tool_access': 'strict'}})
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[call('exec_skill', CALL)]]))
    assert run_row(database, run_id).status == 'waiting_approval'
    assert 'skill.script.started' not in _kinds(database, run_id)
    with database() as db:
        pending = list_pending(db, PRINCIPAL, tenant_id, run_id)
        assert len(pending) == 1
        approval_id = pending[0]['id']
    with database() as db:
        resolve(db, PRINCIPAL, tenant_id, run_id, UUID(approval_id), approve=True)
    resumed = FakeModel([[_text('done')]])
    run_once(database, 'worker', model_factory=lambda _: resumed)
    assert run_row(database, run_id).status == 'completed'
    assert _kinds(database, run_id).count('skill.script.started') == 1
    assert any('hello approved' in m.content for m in resumed.requests[0].messages if m.role == 'tool')
    with database() as db, pytest.raises(Conflict):
        resolve(db, PRINCIPAL, tenant_id, run_id, UUID(approval_id), approve=True)


def test_a_rejected_script_never_starts(database, gate):
    tenant_id, run_id = _worker_run(database, 'reject-1', budgets={'behavior': {'tool_access': 'strict'}})
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[call('exec_skill', CALL)]]))
    with database() as db:
        approval_id = list_pending(db, PRINCIPAL, tenant_id, run_id)[0]['id']
    with database() as db:
        resolve(db, PRINCIPAL, tenant_id, run_id, UUID(approval_id), approve=False)
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[_text('ok')]]))
    assert run_row(database, run_id).status == 'completed'
    assert 'skill.script.started' not in _kinds(database, run_id)
