"""End-to-end script run through the Run store: gate, agent setting, approval-ready tool, audit and events.

Proposal 2026-11-04-skill-scripts, tasks 5.4, 7.3–7.8. The gate is opened by patching the two
configuration readers the platform consults (config flag and auth mode), which is what a development
deployment provides.
"""
import asyncio
from types import SimpleNamespace

import pytest

from nexus_core.platform import Principal
from nexus_platform.errors import NotFound
from nexus_platform.persistence.models import RunRecord
from nexus_platform.runs.preparation import prepare_execution
from nexus_platform.runs.service import claim_next, create_run, list_events
from nexus_platform.runs.store import DurableRuntimeStore
from nexus_platform.sessions.service import create_session
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _agent, _publish, _tenant, _version_for

CODE = 'import json, sys\nargs = json.load(sys.stdin)\nprint("hello", args["text"])\n'
ARGS = '{"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": false}'
SCRIPT_SKILL = ('---\nname: greeter\ndescription: Greets\ntools: []\nscripts: [{"name": "go", "path": "scripts/go.py", '
                '"interpreter": "python3", "args": ' + ARGS + '}]\n---\n# Use the script\n')
TOOLS = ('load_skill', 'read_skill_file', 'run_skill_script')


def _open_gate(monkeypatch):
    import nexus_platform.configuration as configuration
    monkeypatch.setattr(configuration, 'skill_scripts_allowed', lambda *a, **k: True)
    monkeypatch.setattr(configuration, 'auth_settings', lambda *a, **k: SimpleNamespace(mode='development'))


def _run_context(database, budgets=None, tools=TOOLS):
    tenant, model_version = _tenant(database)
    published = _publish(database, tenant, text=SCRIPT_SKILL, files={'scripts/go.py': CODE})
    agent_id = _agent(database, tenant, model_version, [published], tools=tools, budgets=budgets)
    agent_version_id = _version_for(database, tenant, agent_id)
    with database() as db:
        session = create_session(db, PRINCIPAL, tenant.id, agent_version_id=agent_version_id, title='S')
        run, _ = create_run(db, PRINCIPAL, tenant.id, session.id, message='Greet', idempotency_key='g-1')
        run_id, tenant_id = run.id, tenant.id
    with database() as db:
        task = claim_next(db, 'script-worker')
    context = prepare_execution(database, task, 'script-worker')
    return tenant_id, run_id, context, task


def test_gate_open_offers_the_tool_and_runs_the_script_with_events(database, monkeypatch):
    _open_gate(monkeypatch)
    tenant_id, run_id, context, task = _run_context(database)
    assert context is not None and 'run_skill_script' in [name for name, _, _ in context.bindings]
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    text = asyncio.run(store.run_skill_script('greeter', 'go', {'text': 'world'}))
    assert 'hello world' in text and 'exit_code="0"' in text
    with database() as db:
        kinds = [event.event_type for event in list_events(db, PRINCIPAL, tenant_id, run_id, 0)]
    assert 'skill.script.started' in kinds and 'skill.script.completed' in kinds


def test_invalid_arguments_are_refused_without_running(database, monkeypatch):
    _open_gate(monkeypatch)
    tenant_id, run_id, context, task = _run_context(database)
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    text = asyncio.run(store.run_skill_script('greeter', 'go', {'text': 42}))
    assert text == 'Script not run: skill_args_invalid'


def test_gate_closed_hides_the_tool_and_refuses_the_call(database):
    # Without the patch the config file is absent: scripts are off, so the tool is not offered.
    tenant_id, run_id, context, task = _run_context(database)
    assert 'run_skill_script' not in [name for name, _, _ in context.bindings]
    store = DurableRuntimeStore(database, context, 'script-worker', task)
    with pytest.raises(NotFound):
        asyncio.run(store.run_skill_script('greeter', 'go', {'text': 'x'}))


def test_agent_setting_off_hides_the_tool_even_with_the_gate_open(database, monkeypatch):
    _open_gate(monkeypatch)
    _, _, context, _ = _run_context(database, budgets={'behavior': {'skill_scripts': False}})
    assert 'run_skill_script' not in [name for name, _, _ in context.bindings]
