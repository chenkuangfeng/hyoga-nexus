"""Externalized tool output (P2): gateway spill, paged reads bound to the Run, and the rolling view trim."""
import asyncio
import json
import re
from uuid import uuid4

from nexus_core.runtime import ModelChunk, ModelMessage, ToolCall, ToolDefinition, ToolResult
from nexus_core.platform import Principal
from nexus_platform.persistence.models import ToolOutputRecord
from nexus_platform.runs.service import create_run
from nexus_runtimes.native.context.assembly import trim_tool_results
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_tools.builtins.tool_output import tool_output_tools
from nexus_tools.gateway import AuthorizedToolGateway, OutputSpill
from nexus_tools.registry import RegisteredTool, ToolRegistry
from nexus_worker.__main__ import run_once

from test_platform import database  # noqa: F401 (pytest fixture)
from test_native_runtime import FakeModel, call, registry, stack

HANDLE = re.compile(r'artifact:([0-9a-f-]{36})')


class Access:
    """Minimal access port: records what the gateway persists, grants every binding."""
    def __init__(self):
        self.spilled, self.finished = [], []

    async def authorize(self, name, version):
        return 'binding-' + name

    async def start(self, call, binding_id):
        return str(uuid4())

    async def finish(self, invocation_id, status, summary, error_code):
        self.finished.append(summary)

    async def denied(self, name):
        pass

    async def spill(self, invocation_id, content):
        self.spilled.append(content)
        return str(uuid4())


def _echo_registry(output):
    tools = ToolRegistry()
    tools.register(RegisteredTool(ToolDefinition('echo', 'Echo', {'type': 'object', 'properties': {},
        'additionalProperties': False}), lambda arguments, context: ToolResult(output), lambda r: r.data))
    for tool in tool_output_tools():
        tools.register(tool)
    return tools


def _gateway(tools, access, bindings, spill):
    return AuthorizedToolGateway(tools, access, bindings, run_id=str(uuid4()), session_id=str(uuid4()),
                                 tenant_id=str(uuid4()), services=None, spill=spill)


def test_large_output_is_spilled_and_only_preview_reaches_the_run_when_reader_is_bound():
    access = Access()
    gateway = _gateway(_echo_registry('A' * 3000 + 'TAIL'), access, {'echo': 'v1', 'read_tool_output': 'v1'},
                       OutputSpill(inline_limit=2000, preview_chars=50, page_chars=4000))
    result = asyncio.run(gateway.execute(ToolCall('c1', 'echo', '{}'), CancellationToken()))
    assert len(access.spilled) == 1 and access.spilled[0].endswith('TAIL')  # full text went to the store
    assert 'TAIL' not in result.data and result.data.startswith('A' * 50)
    assert HANDLE.search(result.data)
    assert access.finished == [result.data]  # events carry the same public projection


def test_output_within_inline_limit_is_kept_whole_when_reader_is_bound():
    access = Access()
    gateway = _gateway(_echo_registry('B' * 3500), access, {'echo': 'v1', 'read_tool_output': 'v1'},
                       OutputSpill(inline_limit=4000, preview_chars=50, page_chars=4000))
    result = asyncio.run(gateway.execute(ToolCall('c1', 'echo', '{}'), CancellationToken()))
    assert access.spilled == [] and result.data == 'B' * 3500


def test_without_reader_binding_the_previous_4000_char_cap_still_applies():
    access = Access()
    gateway = _gateway(_echo_registry('C' * 5000), access, {'echo': 'v1'},
                       OutputSpill(inline_limit=2000, preview_chars=50, page_chars=4000))
    result = asyncio.run(gateway.execute(ToolCall('c1', 'echo', '{}'), CancellationToken()))
    assert access.spilled == [] and len(result.data) == 4000


def test_reader_output_is_never_externalized():
    access = Access()
    tools = ToolRegistry()
    for tool in tool_output_tools():
        tools.register(RegisteredTool(tool.definition, lambda arguments, context: ToolResult('D' * 3000),
                                      lambda r: r.data))
    gateway = _gateway(tools, access, {'read_tool_output': 'v1'},
                       OutputSpill(inline_limit=2000, preview_chars=50, page_chars=4000))
    result = asyncio.run(gateway.execute(ToolCall('c1', 'read_tool_output', '{"handle":"%s"}' % ('0' * 36)), CancellationToken()))
    assert access.spilled == [] and result.data == 'D' * 3000


def test_trim_keeps_recent_rounds_and_replaces_older_results_with_one_line():
    messages = [
        ModelMessage('user', 'question'),
        ModelMessage('assistant', '', tool_calls=(ToolCall('a', 'echo', '{}'),)),
        ModelMessage('tool', 'first line\nlong body', tool_call_id='a'),
        ModelMessage('assistant', '', tool_calls=(ToolCall('b', 'echo', '{}'),)),
        ModelMessage('tool', 'second result', tool_call_id='b'),
    ]
    trimmed = trim_tool_results(messages, 1)
    assert trimmed[2].content == '[历史工具结果已省略：echo] first line'
    assert trimmed[4].content == 'second result'  # within the window, untouched
    assert messages[2].content == 'first line\nlong body'  # the source history is not modified
    assert trim_tool_results(messages, 2) == messages  # nothing outside a window of 2 rounds


def test_end_to_end_spill_then_page_within_the_same_run(database):
    behavior = {'tool_output_inline_limit': 500, 'tool_preview_chars': 50, 'tool_output_page_chars': 1000}
    principal, tenant, session, run, _ = stack(database, ['echo', 'read_tool_output'], {'max_tokens': 100000, 'behavior': behavior})
    body = 'A' * 1500 + 'SECRET-TAIL'
    async def echo(arguments, context):
        return ToolResult(body)
    tools = registry(echo)
    for tool in tool_output_tools():
        tools.register(tool)

    async def reader_turn():
        # Callable turns are async generators; the handle is only known from the request just sent.
        handle = HANDLE.search(next(m.content for m in model.requests[-1].messages if m.role == 'tool')).group(1)
        yield ModelChunk('tool_call', tool_call=ToolCall('read-1', 'read_tool_output', json.dumps({'handle': handle, 'offset': 0})))
        yield ModelChunk('done', finish_reason='tool_calls')
    model = FakeModel([[call('echo', '{"text":"go"}', id='echo-1')], reader_turn, [ModelChunk('text', text='final')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: tools)

    spilled = next(m.content for m in model.requests[1].messages if m.role == 'tool')
    assert 'SECRET-TAIL' not in spilled and HANDLE.search(spilled)
    page = next(m.content for m in model.requests[2].messages if m.role == 'tool' and m.tool_call_id == 'read-1')
    assert page.startswith('A' * 1000) and 'SECRET-TAIL' not in page
    assert 'offset=1000' in page
    with database() as db:
        row = db.query(ToolOutputRecord).one()
        assert row.content == body and row.size_chars == len(body) and row.run_id == run.id


def test_handle_from_another_run_is_not_found(database):
    behavior = {'tool_output_inline_limit': 500, 'tool_preview_chars': 50, 'tool_output_page_chars': 1000}
    principal, tenant, session, run, _ = stack(database, ['echo', 'read_tool_output'], {'max_tokens': 100000, 'behavior': behavior})
    async def echo(arguments, context):
        return ToolResult('E' * 1000)
    tools = registry(echo)
    for tool in tool_output_tools():
        tools.register(tool)
    first = FakeModel([[call('echo', '{"text":"go"}')], [ModelChunk('text', text='first')]])
    run_once(database, 'worker', model_factory=lambda _: first, registry_factory=lambda _: tools)
    with database() as db:
        handle = str(db.query(ToolOutputRecord.id).scalar())
    with database() as db:
        create_run(db, principal, tenant.id, session.id, message='Again', idempotency_key='again')

    async def reader_turn():
        yield ModelChunk('tool_call', tool_call=ToolCall('read-x', 'read_tool_output', json.dumps({'handle': handle, 'offset': 0})))
        yield ModelChunk('done', finish_reason='tool_calls')
    later = FakeModel([reader_turn, [ModelChunk('text', text='nope')]])
    run_once(database, 'worker', model_factory=lambda _: later, registry_factory=lambda _: tools)
    result = next(m.content for m in later.requests[1].messages if m.role == 'tool' and m.tool_call_id == 'read-x')
    assert result == 'tool_output_not_found'


def test_without_reader_bound_large_result_is_truncated_end_to_end(database):
    principal, tenant, session, run, _ = stack(database, ['echo'])
    async def echo(arguments, context):
        return ToolResult('F' * 5000)
    model = FakeModel([[call('echo', '{"text":"go"}')], [ModelChunk('text', text='ok')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: registry(echo))
    content = next(m.content for m in model.requests[1].messages if m.role == 'tool')
    assert len(content) == 4000 and 'artifact:' not in content
    with database() as db:
        assert db.query(ToolOutputRecord).count() == 0
