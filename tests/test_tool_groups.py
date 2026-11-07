"""Tool groups and two-layer gating (openspec 2026-11-07-tool-expansion, section 1)."""
import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from nexus_core.native import BUILTIN_TOOL_NAMES, GROUP_IDS, TOOL_GROUPS, NativePolicy, group_enabled
from nexus_core.runtime import ToolCall, ToolDefinition, ToolResult
from nexus_platform.runs.tool_gates import GateFacts, hidden_groups, unavailable_groups
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_tools.builtins import builtins
from nexus_tools.builtins.catalog import builtin_catalog, group_catalog
from nexus_tools.gateway import AuthorizedToolGateway
from nexus_tools.registry import RegisteredTool, ToolRegistry


# ------------------------------------------------------------ consistency

def test_registry_names_and_builtin_names_agree():
    registry = builtins()
    names = {entry.name for entry in builtin_catalog()}
    assert names == set(BUILTIN_TOOL_NAMES), 'BUILTIN_TOOL_NAMES and the registered builtins must list the same tools'
    for name in names:
        assert registry.get(name, 'v1').definition.group in GROUP_IDS


def test_every_group_is_declared_once_and_base_is_locked():
    assert len(set(GROUP_IDS)) == len(GROUP_IDS)
    assert next(g for g in TOOL_GROUPS if g.id == 'base').locked
    assert group_enabled({'base': False}, 'base') is True


def test_existing_groups_keep_their_tools():
    groups = {entry.name: entry.group for entry in builtin_catalog()}
    assert groups['todo'] == 'base' and groups['read_tool_output'] == 'base'
    assert groups['search_memory'] == 'memory' and groups['read_conversation'] == 'memory'
    assert groups['search_knowledge'] == 'knowledge' and groups['run_skill_script'] == 'skills'


def test_group_catalog_marks_groups_without_tools_as_planned():
    info = {item['id']: item for item in group_catalog()}
    assert info['base']['tool_count'] >= 4 and info['base']['planned'] == ''
    assert info['wiki']['tool_count'] == 0 and info['wiki']['planned']


# ------------------------------------------------------------ policy

def test_policy_accepts_switchable_groups_only():
    assert NativePolicy(tool_groups_enabled={'sandbox': True}).tool_groups_enabled == {'sandbox': True}
    for bad in ({'base': False}, {'nope': True}, {'sandbox': 'yes'}, ['sandbox']):
        with pytest.raises(ValueError):
            NativePolicy(tool_groups_enabled=bad)


def test_high_impact_groups_default_to_off_and_old_versions_gain_nothing():
    for group in ('sandbox', 'web', 'collab', 'schedule', 'media'):
        assert group_enabled({}, group) is False
        assert group_enabled(None, group) is False
    for group in ('base', 'memory', 'knowledge', 'skills'):
        assert group_enabled({}, group) is True
    assert group_enabled({'sandbox': True}, 'sandbox') is True


# ------------------------------------------------------------ gates

def test_unavailable_groups_report_stable_reasons():
    reasons = unavailable_groups(GateFacts())
    assert reasons == {'sandbox': 'sandbox_disabled', 'wiki': 'wiki_base_not_bound', 'web': 'web_backend_missing'}
    assert unavailable_groups(GateFacts(sandbox_enabled=True))['sandbox'] == 'sandbox_not_accepted'
    assert 'sandbox' not in unavailable_groups(GateFacts(sandbox_enabled=True, sandbox_accepted=True))


def test_switch_cannot_open_an_unavailable_group_and_availability_cannot_open_a_switched_off_one():
    on = {'sandbox': True}
    assert 'sandbox' in hidden_groups(GateFacts(), on)
    ready = GateFacts(sandbox_enabled=True, sandbox_accepted=True)
    assert 'sandbox' not in hidden_groups(ready, on)
    assert 'sandbox' in hidden_groups(ready, {})
    assert 'base' not in hidden_groups(GateFacts(), {})


# ------------------------------------------------------------ gateway

class _Access:
    def __init__(self):
        self.denied_names = []

    async def authorize(self, name, version):
        return 'binding'

    async def start(self, call, binding_id):
        return 'inv'

    async def finish(self, *args):
        return None

    async def denied(self, name):
        self.denied_names.append(name)


def _registry():
    tools = ToolRegistry()
    schema = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    for name, group in (('plain', 'base'), ('boxed', 'sandbox')):
        tools.register(RegisteredTool(ToolDefinition(name, name, schema, risk='read', group=group),
                                      lambda args, context: ToolResult('ran'), lambda r: r.data))
    return tools


def _gateway(hidden):
    access = _Access()
    return AuthorizedToolGateway(_registry(), access, {'plain': 'v1', 'boxed': 'v1'}, run_id='r', session_id='s',
                                 tenant_id='t', hidden_groups=frozenset(hidden)), access


def test_gateway_does_not_offer_or_run_tools_of_hidden_groups():
    gateway, access = _gateway({'sandbox'})
    assert [d.name for d in asyncio.run(gateway.definitions())] == ['plain']
    result = asyncio.run(gateway.execute(ToolCall('c', 'boxed', '{}'), CancellationToken()))
    assert result.error_code == 'tool_authorization_denied' and access.denied_names == ['boxed']
    assert asyncio.run(gateway.execute(ToolCall('c', 'plain', '{}'), CancellationToken())).data == 'ran'


def test_gateway_offers_every_bound_tool_when_no_group_is_hidden():
    gateway, _ = _gateway(set())
    assert [d.name for d in asyncio.run(gateway.definitions())] == ['boxed', 'plain']


# ------------------------------------------------------------ definition metadata

def test_group_and_scheduling_metadata_do_not_change_the_definition_digest():
    base = ToolDefinition('t', 'd', {'type': 'object'})
    other = replace(base, group='sandbox', source='domain', concurrency=lambda args: None, deferrable=True)
    # The engine digests str(definitions) to detect a changed tool block; metadata must not move it.
    assert str(base) == str(other)


@pytest.mark.parametrize('kwargs', [{'group': 'Bad Group'}, {'group': ''}, {'source': 'plugin'}])
def test_definition_rejects_invalid_group_or_source(kwargs):
    with pytest.raises(ValueError):
        ToolDefinition('t', 'd', {'type': 'object'}, **kwargs)
