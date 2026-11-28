"""Process-wide builtin registry: one definition set, run state supplied per invocation only."""
import asyncio

import pytest

from nexus_core.runtime import RuntimeFault
from nexus_tools.builtins import builtins
from nexus_tools.builtins.checkpoint import checkpoint_tool
from nexus_tools.gateway import prepare_arguments
from nexus_tools.registry import ToolContext


class FakeStore:
    def __init__(self):
        self.saved = []

    async def checkpoint(self, content):
        self.saved.append(content)


class Cancel:
    def cancelled(self):
        return False


def _context(services):
    return ToolContext('inv', 'run', 'session', 'tenant', Cancel(), services)


def test_builtins_registry_is_built_once_per_process():
    assert builtins() is builtins()


def test_checkpoint_writes_to_the_store_of_the_invoking_run_only():
    tool, first, second = checkpoint_tool(), FakeStore(), FakeStore()
    asyncio.run(tool.handler({'content': 'alpha'}, _context(first)))
    asyncio.run(tool.handler({'content': 'beta'}, _context(second)))
    assert first.saved == ['alpha'] and second.saved == ['beta']


def test_checkpoint_exposes_one_canonical_alias_and_prefers_it_for_legacy_conflicts():
    tool, store = checkpoint_tool(), FakeStore()
    assert tool.definition.parameters['properties'].keys() == {'key_info'}
    assert tool.definition.parameters['required'] == ['key_info']
    arguments, error = prepare_arguments(tool, '{"key_info":"canonical","content":"legacy"}')
    assert error is None and arguments == {'key_info': 'canonical'}
    result = asyncio.run(tool.handler(arguments, _context(store)))
    assert not result.error_code
    assert store.saved == ['canonical']


def test_checkpoint_accepts_legacy_content_argument():
    tool, store = checkpoint_tool(), FakeStore()
    arguments, error = prepare_arguments(tool, '{"content":"legacy"}')
    assert error is None and arguments == {'key_info': 'legacy'}
    asyncio.run(tool.handler(arguments, _context(store)))
    assert store.saved == ['legacy']


def test_builtin_without_services_fails_closed():
    tool = checkpoint_tool()
    with pytest.raises(RuntimeFault) as caught:
        asyncio.run(tool.handler({'content': 'x'}, _context(None)))
    assert caught.value.code == 'tool_unavailable'
