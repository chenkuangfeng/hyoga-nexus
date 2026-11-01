"""Process-wide builtin registry: one definition set, run state supplied per invocation only."""
import asyncio

import pytest

from nexus_core.runtime import RuntimeFault
from nexus_tools.builtins import builtins
from nexus_tools.builtins.checkpoint import checkpoint_tool
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


def test_builtin_without_services_fails_closed():
    tool = checkpoint_tool()
    with pytest.raises(RuntimeFault) as caught:
        asyncio.run(tool.handler({'content': 'x'}, _context(None)))
    assert caught.value.code == 'tool_unavailable'
