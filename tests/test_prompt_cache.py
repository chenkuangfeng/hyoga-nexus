"""Prefix stability, protocol cache boundaries and unchanged source/permission contracts."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from nexus_core.native import NativePolicy
from nexus_core.runtime import ModelMessage, ModelRequest, ToolCall, ToolDefinition
from nexus_runtimes.native.context.assembler import ContextAssembler
from nexus_runtimes.native.models.openai_compatible import OpenAICompatibleModel
from nexus_runtimes.native.models.protocols.structured import StructuredModel
from nexus_platform.runs.context_catalogs import KnowledgeCatalogProvider


def definitions(reverse=False):
    schema = {'type': 'object', 'properties': {'z': {'type': 'string'}, 'a': {'type': 'integer'}},
              'required': ['z', 'a']}
    if reverse:
        schema = {'required': ['z', 'a'], 'properties': {'a': {'type': 'integer'}, 'z': {'type': 'string'}},
                  'type': 'object'}
    tools = [ToolDefinition('z_read', 'read z', schema), ToolDefinition('a_read', 'read a', schema)]
    return tuple(reversed(tools)) if reverse else tuple(tools)


def wire_payload(protocol, request):
    """Exercise the actual adapter serialization with a valid non-stream response."""
    sent = []
    async def scenario():
        def handler(http_request):
            sent.append(json.loads(http_request.content))
            if protocol == 'anthropic_messages':
                reply = {'content': [{'type': 'text', 'text': 'OK'}], 'stop_reason': 'end_turn',
                         'usage': {'input_tokens': 10, 'cache_read_input_tokens': 20,
                                   'cache_creation_input_tokens': 30, 'output_tokens': 2}}
            elif protocol == 'openai_responses':
                reply = {'status': 'completed', 'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': 'OK'}]}]}
            else:
                reply = {'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': 'test',
                         'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'OK'},
                                      'finish_reason': 'stop'}]}
            return httpx.Response(200, json=reply)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        if protocol == 'openai_chat_completions':
            model = OpenAICompatibleModel(model='test', api_key='test', http_client=client, options={'stream': False})
        else:
            model = StructuredModel(model='test', api_key='test', base_url='https://model.example/v1',
                                    protocol=protocol, http_client=client, options={'stream': False})
        try:
            return [chunk async for chunk in model.stream(request)]
        finally:
            await model.close()
    chunks = asyncio.run(scenario())
    return sent[0], chunks


@pytest.mark.parametrize('protocol', ['openai_chat_completions', 'openai_responses', 'anthropic_messages'])
def test_wire_tools_are_identical_despite_registration_and_dictionary_order(protocol):
    history = (ModelMessage('system', 'fixed rules'), ModelMessage('user', 'hello'))
    first, _ = wire_payload(protocol, ModelRequest(history, definitions(), 100))
    second, _ = wire_payload(protocol, ModelRequest(history, definitions(True), 100))
    assert json.dumps(first['tools']) == json.dumps(second['tools'])
    tool = first['tools'][0]
    schema = tool.get('input_schema', tool.get('parameters', tool.get('function', {}).get('parameters')))
    assert schema['required'] == ['z', 'a']  # schema arrays retain their original meaning/order


def test_anthropic_cache_uses_at_most_four_ephemeral_boundaries_and_keeps_sources():
    tools = definitions()
    original = deepcopy(tools[0].parameters)
    messages = (ModelMessage('system', 'fixed rules'), ModelMessage('user', 'question'),
                ModelMessage('assistant', '', (ToolCall('c1', 'a_read', '{}'),)),
                ModelMessage('tool', 'result', tool_call_id='c1'))
    payload, chunks = wire_payload('anthropic_messages', ModelRequest(messages, tools, 100))
    assert payload['system'] == [{'type': 'text', 'text': 'fixed rules', 'cache_control': {'type': 'ephemeral'}}]
    assert payload['tools'][-1]['cache_control'] == {'type': 'ephemeral'}
    def controls(value):
        if isinstance(value, dict):
            return int('cache_control' in value) + sum(controls(v) for v in value.values())
        return sum(controls(v) for v in value) if isinstance(value, list) else 0
    assert controls(payload) == 4
    assert payload['messages'][-1]['content'][0]['type'] == 'tool_result'
    assert tools[0].parameters == original
    assert messages[-1].content == 'result'
    usage = next(chunk for chunk in chunks if chunk.kind == 'usage')
    assert usage.usage == {'input': 10, 'cache_read': 20, 'cache_creation': 30, 'output': 2}
    assert usage.total_tokens == 62


@pytest.mark.parametrize('protocol', ['openai_chat_completions', 'openai_responses'])
def test_other_protocols_never_receive_anthropic_fields(protocol):
    payload, _ = wire_payload(protocol, ModelRequest((ModelMessage('system', 'rules'), ModelMessage('user', 'hi')),
                                                    definitions(), 100))
    assert 'cache_control' not in json.dumps(payload)


def test_default_view_keeps_complete_history_before_changing_runtime_reference():
    history = [ModelMessage('system', 'rules'), ModelMessage('user', 'question'),
               ModelMessage('assistant', '', (ToolCall('c1', 'read', '{}'),)),
               ModelMessage('tool', 'result', tool_call_id='c1')]
    assembler = ContextAssembler(None, None, NativePolicy())
    assembler.freeze(())
    working = SimpleNamespace(anchor=lambda turn: f'Runtime reference {turn}')
    first = assembler.view(history, working=working, turn=1).messages
    second = assembler.view(history, working=working, turn=2).messages
    assert first[:-1] == second[:-1] == history
    assert first[-1].content != second[-1].content
    legacy = ContextAssembler(None, None, NativePolicy(working_memory_tail=False))
    legacy.freeze(())
    assert legacy.view(history, working=working, turn=1).messages[1].content == 'Runtime reference 1'


def test_knowledge_catalog_ignores_pin_order_but_preserves_current_visibility(monkeypatch):
    from nexus_platform.knowledge import access, tools
    ids = [UUID(int=2), UUID(int=1)]
    bases = [SimpleNamespace(id=id, name=f'base-{id.int}', settings={}, description='description') for id in ids]
    monkeypatch.setattr(tools, 'bound_base_ids', lambda *_: ids)
    monkeypatch.setattr(access, 'readable_bases', lambda *_: bases)
    provider = KnowledgeCatalogProvider()
    run = SimpleNamespace(tenant_id=UUID(int=3), principal_id=UUID(int=4))
    version = SimpleNamespace(id=UUID(int=5))
    first = provider.build(None, run, version)[1][0]
    bases.reverse()
    assert provider.build(None, run, version)[1][0] == first
    bases.pop()
    assert provider.build(None, run, version)[1][0] != first


def test_resident_selection_and_order_survive_usage_changes_but_respect_disable():
    from dataclasses import replace
    from datetime import datetime, timezone
    import re
    from nexus_memory import service
    from nexus_memory.ports import EntryView, VersionView
    from test_memory_rules import FakeRepo

    repo = FakeRepo()
    tenant, owner = UUID(int=10), UUID(int=11)
    now = datetime(2026, 11, 28, tzinfo=timezone.utc)
    for number in range(1, 4):
        entry = EntryView(UUID(int=number), tenant, owner, 'profile', f'profile {number}', '', True, 1)
        repo.entries[entry.id] = entry
        repo.versions[(entry.id, 1)] = VersionView(entry.id, 1, str(number) * 450, None, None)
    def resident():
        result = service.snapshot(repo, tenant, owner, now=now)
        # The retrieval index may change by usage; only the constant resident prefix is compared.
        block = re.search(r'<user_memory.*?</user_memory>', result.text, re.S).group(0)
        return result, block
    first, first_block = resident()
    assert [row['id'] for row in first.resident] == [str(UUID(int=1)), str(UUID(int=2))]
    repo.touch([UUID(int=3)], now)  # touch an excluded profile, then reverse publication order
    repo.order = {UUID(int=number): number for number in range(1, 4)}
    second, second_block = resident()
    assert second.resident == first.resident and second_block == first_block
    repo.entries[UUID(int=1)] = replace(repo.entries[UUID(int=1)], enabled=False)
    third, third_block = resident()
    assert third_block != first_block
    assert str(UUID(int=1)) not in {row['id'] for row in third.resident}


def test_tail_references_cannot_make_compaction_discard_the_actual_latest_question():
    from nexus_core.runtime import RuntimeFault
    from nexus_core.runtime.context import ContextBlock
    from nexus_core.runtime.context_assembly import RequestContextAssembler
    from nexus_runtimes.native.context.history import compact_history

    question = 'CURRENT QUESTION ' * 400
    history = (ModelMessage('user', 'old question ' * 200), ModelMessage('assistant', 'old answer'),
               ModelMessage('user', question))
    blocks = (ContextBlock('agent', 'agent', 'system', 'system_static', 0, 'rules'),
              ContextBlock('session:checkpoint', 'checkpoint', 'user', 'turn_tail', 40, 'short state'))
    assembled = RequestContextAssembler().assemble(blocks, history).messages
    assert assembled[-1].context_source == 'session:checkpoint'
    # The current question alone is over budget: refusing is safer than replacing it with excerpts.
    with pytest.raises(RuntimeFault, match='model_context_exceeded'):
        compact_history(assembled, 400)


def test_summary_compaction_keeps_latest_question_and_runtime_references():
    from nexus_core.runtime import ExecutionBudget, ModelChunk
    from nexus_runtimes.native.context.compaction import compact
    from nexus_runtimes.native.engine.cancellation import CancellationToken

    class SummaryModel:
        async def stream(self, request):
            assert 'LATEST QUESTION' not in request.messages[-1].content
            yield ModelChunk('text', text='Earlier verified facts')
            yield ModelChunk('done', finish_reason='stop')
    history = (ModelMessage('system', 'rules'), ModelMessage('user', 'old question ' * 400),
               ModelMessage('assistant', 'old answer'), ModelMessage('user', 'LATEST QUESTION'),
               ModelMessage('user', 'checkpoint reference', context_source='session:checkpoint'))
    class SummaryStore:
        async def save_progress(self, _):
            pass
        async def emit(self, *_):
            raise AssertionError('The valid summary should not need a degraded fallback')
    recent, removed = asyncio.run(compact(SummaryModel(), history, 300, CancellationToken(),
                                         ExecutionBudget(), SimpleNamespace(tokens=0), SummaryStore(),
                                         high=200, low=250))
    assert removed == 2
    assert recent[-2:] == history[-2:]
