"""Tool-call hardening (openspec 2026-11-06-tool-call-hardening).

Section 1, argument tolerance: JSON repair with truncation detection, schema-guided coercion, readable
validation errors, and the gateway preparing arguments before approval.
"""
import asyncio
import json
from uuid import uuid4

import pytest

from nexus_core.runtime import ToolCall, ToolDefinition, ToolResult
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_tools import arguments
from nexus_tools.gateway import AuthorizedToolGateway
from nexus_tools.registry import RegisteredTool, ToolRegistry


# ---------------------------------------------------------------- 1.1 repair_json

@pytest.mark.parametrize('text, expected', [
    ('{"a": 1,}', {'a': 1}),
    ('{"a": [1, 2,],}', {'a': [1, 2]}),
    ('{"path": "C:\\dir"}', {'path': 'C:\\dir'}),
    ('{"a": 1} trailing words', {'a': 1}),
    ('{"a": 1}\n{"b": 2}', {'a': 1}),
    ("{'a': 'x'}", {'a': 'x'}),
    ('"a": 1', {'a': 1}),
])
def test_repairs_unambiguous_malformations(text, expected):
    repaired, truncated = arguments.repair_json(text)
    assert truncated is False and json.loads(repaired) == expected


@pytest.mark.parametrize('text', ['{"a": "unterminated', '{"a": [1, 2', '{bad', '{"a": {"b": 1}'])
def test_unclosed_strings_or_brackets_are_reported_as_truncated(text):
    assert arguments.repair_json(text)[1] is True


def test_empty_text_is_an_empty_object():
    assert arguments.repair_json('  ') == ('{}', False)


# ---------------------------------------------------------------- 1.2 coerce

SCHEMA = {
    'type': 'object',
    'properties': {
        'count': {'type': 'integer'}, 'ratio': {'type': 'number'}, 'flag': {'type': 'boolean'},
        'tags': {'type': 'array', 'items': {'type': 'string'}},
        'options': {'type': 'object', 'properties': {'ids': {'type': 'array', 'items': {'type': 'integer'}}}},
        'maybe': {'type': ['string', 'null']}, 'name': {'type': 'string'},
        'ref': {'$ref': '#/$defs/limit'},
    },
    '$defs': {'limit': {'type': 'integer'}},
}


def test_scalars_containers_and_single_values_are_coerced():
    out = arguments.coerce({'count': '5', 'ratio': '0.5', 'flag': 'TRUE', 'tags': 'one', 'maybe': 'null',
                            'options': '{"ids": "[1, 2]"}', 'ref': '7', 'name': '5'}, SCHEMA)
    assert out == {'count': 5, 'ratio': 0.5, 'flag': True, 'tags': ['one'], 'maybe': None,
                   'options': {'ids': [1, 2]}, 'ref': 7, 'name': '5'}


def test_uncertain_values_are_kept_for_validation_to_report():
    original = {'count': '5.5', 'flag': 'yes', 'tags': '[unclosed', 'unknown': '1'}
    out = arguments.coerce(original, SCHEMA)
    assert out == {'count': '5.5', 'flag': 'yes', 'tags': ['[unclosed'], 'unknown': '1'}
    assert original['tags'] == '[unclosed'  # the input is not mutated
    assert arguments.coerce({'count': 'inf'}, SCHEMA) == {'count': 'inf'}


# ---------------------------------------------------------------- 1.3 describe_errors

def test_errors_name_paths_and_reasons_without_values():
    schema = {'type': 'object', 'required': ['query'], 'additionalProperties': False,
              'properties': {'query': {'type': 'string', 'maxLength': 5}, 'limit': {'type': 'integer', 'maximum': 10}}}
    text = arguments.describe_errors(schema, {'limit': 99, 'secret': 'TOP-SECRET-VALUE'})
    assert '参数 (根)：缺少必填字段 query' in text and '参数 limit：不能大于 10' in text
    assert '不允许的字段 secret' in text and 'TOP-SECRET-VALUE' not in text
    assert arguments.describe_errors(schema, {'query': 'ok'}) == ''


def test_error_text_is_bounded():
    schema = {'type': 'object', 'properties': {f'p{i}': {'type': 'integer'} for i in range(20)}}
    text = arguments.describe_errors(schema, {f'p{i}': 'x' for i in range(20)})
    assert text.count('参数 ') == arguments.MAX_ERRORS and '另有 15 处错误' in text
    assert len(text) <= arguments.MAX_ERROR_CHARS


# ---------------------------------------------------------------- 1.4 gateway

class Access:
    def __init__(self, approval_result=None):
        self.started, self.approvals, self.approval_result = [], [], approval_result

    async def authorize(self, name, version):
        return 'binding-' + name

    async def start(self, call, binding_id):
        self.started.append(call.arguments)
        return str(uuid4())

    async def finish(self, invocation_id, status, summary, error_code):
        pass

    async def denied(self, name):
        pass

    async def approval(self, call):
        self.approvals.append(call.arguments)
        return self.approval_result if self.approval_result is not None else call.arguments


def _gateway(access, *, requires_approval=False):
    seen = []

    def handler(args, context):
        seen.append(args)
        return ToolResult('ok')
    tools = ToolRegistry()
    tools.register(RegisteredTool(ToolDefinition('count', 'Count', {
        'type': 'object', 'required': ['n'], 'additionalProperties': False,
        'properties': {'n': {'type': 'integer', 'minimum': 1}, 'tags': {'type': 'array', 'items': {'type': 'string'}}}},
        requires_approval=requires_approval), handler, lambda r: r.data))
    gateway = AuthorizedToolGateway(tools, access, {'count': 'v1'}, run_id=str(uuid4()), session_id=str(uuid4()),
                                    tenant_id=str(uuid4()))
    return gateway, seen


def _run(gateway, text):
    return asyncio.run(gateway.execute(ToolCall('c1', 'count', text), CancellationToken()))


def test_gateway_repairs_and_coerces_before_running():
    access = Access()
    gateway, seen = _gateway(access)
    assert _run(gateway, '{"n": "3", "tags": "a",}').error_code is None
    assert seen == [{'n': 3, 'tags': ['a']}] and json.loads(access.started[0]) == {'n': 3, 'tags': ['a']}


def test_gateway_reports_truncation_and_field_errors():
    gateway, seen = _gateway(Access())
    truncated = _run(gateway, '{"n": 3, "tags": ["a"')
    assert truncated.error_code == 'tool_arguments_truncated' and seen == []
    invalid = _run(gateway, '{"n": 0, "extra": 1}')
    assert invalid.error_code == 'tool_arguments_invalid'
    assert '参数 n：不能小于 1' in invalid.data and '不允许的字段 extra' in invalid.data


def test_approval_sees_normalized_arguments_and_edited_arguments_are_checked_again():
    access = Access()
    gateway, seen = _gateway(access, requires_approval=True)
    _run(gateway, '{"n": "2"}')
    assert json.loads(access.approvals[0]) == {'n': 2} and seen == [{'n': 2}]
    invalid_before = Access()
    gateway, seen = _gateway(invalid_before, requires_approval=True)
    assert _run(gateway, '{"n": "zero"}').error_code == 'tool_arguments_invalid'
    assert invalid_before.approvals == []          # invalid arguments never reach a person
    edited = Access(approval_result='{"n": -1}')
    gateway, seen = _gateway(edited, requires_approval=True)
    assert _run(gateway, '{"n": 1}').error_code == 'tool_arguments_invalid' and seen == []
