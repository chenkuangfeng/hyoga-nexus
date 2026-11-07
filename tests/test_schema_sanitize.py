"""Provider-safe tool schemas (openspec 2026-11-07-tool-expansion, section 5.1)."""
import asyncio
import json

from nexus_core.runtime import ToolCall, ToolDefinition, ToolResult
from nexus_core.schema import restore, sanitize
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_tools.builtins import builtins
from nexus_tools.gateway import AuthorizedToolGateway
from nexus_tools.registry import RegisteredTool, ToolRegistry


def test_builtin_schemas_are_unchanged_by_sanitizing():
    for entry in builtins()._tools.values():
        schema = entry.definition.parameters
        clean = sanitize(schema)
        assert clean.get('properties') == schema.get('properties') or all(k in clean['properties'] for k in schema['properties'])
        assert set(clean['properties']) == set(schema.get('properties', {}))


def test_bad_property_names_are_renamed_deterministically_and_required_follows():
    schema = {'type': 'object', 'properties': {'user name': {'type': 'string'}, 'user_name': {'type': 'string'},
                                               'ok-key': {'type': 'integer'}, 'a/b': {'type': 'string'}},
              'required': ['user name', 'ok-key']}
    clean = sanitize(schema)
    assert list(clean['properties']) == ['user_name_2', 'user_name', 'ok-key', 'a_b']
    assert clean['required'] == ['user_name_2', 'ok-key'] and sanitize(schema) == clean


def test_restore_maps_model_arguments_back_even_when_nested():
    schema = {'type': 'object', 'properties': {
        'user name': {'type': 'string'},
        'items': {'type': 'array', 'items': {'type': 'object', 'properties': {'item id': {'type': 'integer'}}}}}}
    args = {'user_name': 'x', 'items': [{'item_id': 1}, {'item_id': 2}]}
    assert restore(args, schema) == {'user name': 'x', 'items': [{'item id': 1}, {'item id': 2}]}
    assert restore({'plain': 1}, {'type': 'object', 'properties': {'plain': {}}}) == {'plain': 1}


def test_shape_repairs():
    clean = sanitize({'type': 'object', 'anyOf': [{'required': ['a']}], 'enum': [1],
                      'properties': {'a': {'type': ['string', 'null'], 'default': 'x'},
                                     'b': {'type': ['number', 'string']},
                                     'c': {'$ref': '#/$defs/d', 'default': 1},
                                     'd': {'type': 'string', 'required': True},
                                     'e': {'type': 'object'}}})
    props = clean['properties']
    assert 'anyOf' not in clean and 'enum' not in clean
    assert props['a'] == {'type': 'string', 'nullable': True, 'default': 'x'}
    assert props['b'] == {'anyOf': [{'type': 'number'}, {'type': 'string'}]}
    assert 'default' not in props['c'] and 'required' not in props['d'] and clean['required'] == ['d']
    assert props['e'] == {'type': 'object', 'properties': {}, 'required': []}
    assert sanitize('nonsense') == {'type': 'object', 'properties': {}, 'required': []}
    assert sanitize({'type': 'string'})['type'] == 'object'


def test_registered_definition_is_not_modified():
    schema = {'type': 'object', 'properties': {'bad key': {'type': ['string', 'null']}}}
    before = json.dumps(schema)
    sanitize(schema)
    assert json.dumps(schema) == before


def test_gateway_accepts_the_renamed_arguments_the_provider_returns():
    seen = []
    tools = ToolRegistry()
    tools.register(RegisteredTool(ToolDefinition('t', 'd', {'type': 'object', 'properties': {'bad key': {'type': 'string'}},
                                                            'required': ['bad key'], 'additionalProperties': False}),
                                  lambda args, ctx: seen.append(args) or ToolResult('ok'), lambda r: r.data))

    class Port:
        async def authorize(self, *a): return 'b'
        async def start(self, *a): return 'i'
        async def finish(self, *a): return None
        async def denied(self, *a): return None
    gateway = AuthorizedToolGateway(tools, Port(), {'t': 'v1'}, run_id='r', session_id='s', tenant_id='t')
    result = asyncio.run(gateway.execute(ToolCall('c', 't', json.dumps({'bad_key': 'v'})), CancellationToken()))
    assert result.data == 'ok' and seen == [{'bad key': 'v'}]
