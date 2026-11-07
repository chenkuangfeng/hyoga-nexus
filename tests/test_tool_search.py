"""Progressive tool loading (openspec 2026-11-07-tool-expansion, section 5.2-5.3)."""
import asyncio
import json
from uuid import uuid4

from nexus_core.runtime import ToolCall, ToolDefinition, ToolResult
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_tools import bridge
from nexus_tools.gateway import AuthorizedToolGateway
from nexus_tools.registry import RegisteredTool, ToolRegistry


class Port:
    def __init__(self, approve=True):
        self.started, self.approvals, self.denied_names = [], [], []

    async def authorize(self, name, version):
        if name == 'forbidden':
            from nexus_core.runtime import RuntimeFault
            raise RuntimeFault('tool_authorization_denied')
        return 'b-' + name

    async def start(self, call, binding_id):
        self.started.append(call.name)
        return str(uuid4())

    async def finish(self, *args):
        return None

    async def denied(self, name):
        self.denied_names.append(name)

    async def approval(self, call, **kwargs):
        self.approvals.append(call.name)
        return call.arguments


def make(min_tokens=100, bind=None, access='standard'):
    tools, seen = ToolRegistry(), []
    big = {'type': 'object', 'properties': {f'field_{i}': {'type': 'string', 'description': 'x' * 60} for i in range(8)},
           'additionalProperties': False}
    def add(name, description, **kwargs):
        tools.register(RegisteredTool(ToolDefinition(name, description, big, **kwargs),
                                      lambda args, ctx, name=name: seen.append((name, args)) or ToolResult(f'{name} ran'), lambda r: r.data))
    add('weather_lookup', 'Look up the weather forecast for a city', source='mcp', read_only=True, idempotent=True)
    add('stock_quote', 'Fetch a stock price quote', source='mcp', read_only=True, idempotent=True)
    add('delete_all', 'Delete everything on the remote server', source='mcp', side_effects=True, risk='destructive')
    add('forbidden', 'Not authorized for this agent', source='mcp', read_only=True, idempotent=True)
    add('local_tool', 'A normal builtin tool', read_only=True, idempotent=True)
    port = Port()
    names = bind or ['weather_lookup', 'stock_quote', 'delete_all', 'forbidden', 'local_tool']
    gateway = AuthorizedToolGateway(tools, port, {n: 'v1' for n in names}, run_id='r', session_id='s', tenant_id='t',
                                    defer_min_tokens=min_tokens, tool_access=access)
    return gateway, port, seen


def run(gateway, tool, **arguments):
    return asyncio.run(gateway.execute(ToolCall(str(uuid4()), tool, json.dumps(arguments)), CancellationToken()))


def test_heavy_deferrable_tools_are_replaced_by_the_bridge():
    gateway, _, _ = make()
    names = [d.name for d in asyncio.run(gateway.definitions())]
    assert names == ['local_tool', 'tool_call', 'tool_describe', 'tool_search']
    listing = next(d for d in asyncio.run(gateway.definitions()) if d.name == 'tool_search').description
    assert 'weather_lookup' in listing and 'stock_quote' in listing and 'forbidden' not in listing


def test_below_the_threshold_or_when_off_nothing_changes():
    for tokens in (0, 10_000_000):
        gateway, _, _ = make(min_tokens=tokens)
        names = {d.name for d in asyncio.run(gateway.definitions())}
        assert 'tool_search' not in names and {'weather_lookup', 'delete_all', 'local_tool'} <= names


def test_the_tool_block_is_identical_on_every_listing_and_for_any_binding_order():
    first, _, _ = make()
    second, _, _ = make(bind=['local_tool', 'forbidden', 'delete_all', 'stock_quote', 'weather_lookup'])
    assert asyncio.run(first.definitions()) == asyncio.run(first.definitions()) == asyncio.run(second.definitions())


def test_search_describe_and_call_flow():
    gateway, port, seen = make()
    asyncio.run(gateway.definitions())
    found = run(gateway, 'tool_search', queries=['weather forecast'])
    assert 'weather_lookup' in found.data and 'stock_quote' not in found.data
    described = json.loads(run(gateway, 'tool_describe', names=['weather_lookup']).data)
    assert described['name'] == 'weather_lookup' and 'field_0' in described['parameters']['properties']
    assert 'not an available tool' in run(gateway, 'tool_describe', names=['nope']).data
    result = run(gateway, 'tool_call', name='weather_lookup', arguments={'field_0': 'Beijing'})
    assert result.data == 'weather_lookup ran' and seen == [('weather_lookup', {'field_0': 'Beijing'})]
    assert 'weather_lookup' in port.started  # the real tool is recorded under its own name


def test_a_resumed_gateway_serves_the_bridge_before_listing_tools():
    gateway, _, seen = make()
    assert run(gateway, 'tool_call', name='stock_quote', arguments={}).data == 'stock_quote ran'


def test_tool_call_cannot_reach_unbound_unauthorized_or_directly_offered_tools():
    gateway, _, seen = make(bind=['weather_lookup', 'forbidden', 'local_tool'])
    asyncio.run(gateway.definitions())
    for name in ('stock_quote', 'forbidden', 'local_tool', 'tool_search', 'nonsense'):
        assert run(gateway, 'tool_call', name=name, arguments={}).error_code == 'tool_not_registered'
    assert seen == []


def test_the_real_tool_still_passes_access_level_and_approval():
    gateway, port, seen = make(access='read_only')
    asyncio.run(gateway.definitions())
    assert run(gateway, 'tool_call', name='delete_all', arguments={}).error_code == 'tool_not_registered'  # hidden from read_only
    standard, port, seen = make()
    asyncio.run(standard.definitions())
    run(standard, 'tool_call', name='delete_all', arguments={})
    assert port.approvals == ['delete_all'] and seen == [('delete_all', {})]  # destructive asks, under its own name


def test_arguments_are_validated_against_the_real_schema():
    gateway, _, seen = make()
    asyncio.run(gateway.definitions())
    bad = run(gateway, 'tool_call', name='weather_lookup', arguments={'unknown_field': 1})
    assert bad.error_code == 'tool_arguments_invalid' and seen == []
    as_text = run(gateway, 'tool_call', name='weather_lookup', arguments=json.dumps({'field_1': 'x'}))
    assert as_text.data == 'weather_lookup ran'


def test_search_ranking_prefers_name_matches_and_lists_everything_for_an_empty_query():
    catalog = {'weather_lookup': ToolDefinition('weather_lookup', 'city forecast', {'type': 'object'}),
               'stock_quote': ToolDefinition('stock_quote', 'price of a weather derivative', {'type': 'object'})}
    assert bridge.search(catalog, ['weather'], 5) == ['weather_lookup', 'stock_quote']
    assert bridge.search(catalog, [''], 5) == ['stock_quote', 'weather_lookup']
    assert bridge.search(catalog, ['zzz'], 5) == []
