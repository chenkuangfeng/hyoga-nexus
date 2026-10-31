"""Behavior tests for GA/WeKnora translation boundaries; mocks do not imply online acceptance."""
import asyncio
import json
from dataclasses import asdict
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from test_platform import database
from test_model_settings import settings_client, add_provider, add_model
from test_native_runtime import stack, FakeModel, call, run_row
from nexus_core.native import NativePolicy, HookTransform
from nexus_core.runtime import ModelChunk, ModelMessage, RuntimeFault, ToolDefinition, ToolResult, RuntimeProgress
from nexus_runtimes.native.engine import NativeEngine, CancellationToken
from nexus_runtimes.native.hooks import HookRegistry
from nexus_runtimes.native.models.retry import RetryModel
from nexus_runtimes.native.models.routing import RoutedModel
from nexus_runtimes.native.models.protocols.structured import StructuredModel
from nexus_runtimes.native.models.tool_protocol import parse_text_calls
from nexus_platform.persistence.models import InputRequestRecord, NativeRunStateRecord, MessageRecord, ToolInvocationRecord, SessionRecord, MemoryVersionRecord
from nexus_tools.registry import ToolRegistry, RegisteredTool
from nexus_worker.__main__ import run_once


class Store:
    def __init__(self): self.events, self.messages = [], []
    async def emit(self, name, data): self.events.append((name, data))
    async def message(self, value): self.messages.append(value)
    async def save_progress(self, value): pass
class Tools:
    async def definitions(self): return ()


def test_empty_and_code_recovery_and_completion_hooks(database):
    principal, tenant, session, run, _ = stack(database)
    model = FakeModel([[], [ModelChunk('text', text='```python\n' + 'print(1)\n' * 10 + '```')],
                       [ModelChunk('text', text='This code is only an example; no execution is needed.')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    assert run_row(database, run.id).status == 'completed'
    assert len(model.requests) == 3
    assert any('Blank response' in message.content for message in model.requests[1].messages)
    async def scenario():
        hooks = HookRegistry()
        async def before(context):
            return HookTransform((ModelMessage('user', 'Authorized project context'),), ('Report verified final evidence.',))
        hooks.register('agent.before', before)
        memory = Store()
        model = FakeModel([[ModelChunk('text', text='first')], [ModelChunk('text', text='final evidence')]])
        from nexus_core.runtime import ExecutionBudget
        result = await NativeEngine(model, Tools(), memory, transforms=hooks).run('run',
            (ModelMessage('system', 'Help'), ModelMessage('user', 'Task')), CancellationToken(), ExecutionBudget(max_tokens=100000))
        assert result.status == 'completed'
        assert len(model.requests) == 2
        assert any(m.content == 'Authorized project context' for m in model.requests[0].messages)
        assert any(m.content == 'Report verified final evidence.' for m in model.requests[1].messages)
    asyncio.run(scenario())


def test_empty_never_succeeds_and_candidate_checkpoint_compatibility(database):
    principal, tenant, session, run, _ = stack(database)
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[], [], []]))
    assert run_row(database, run.id).error_code == 'model_response_unusable'
    principal, tenant, session, run, _ = stack(database, ['ask_user', 'update_working_checkpoint'])
    model = FakeModel([[call('update_working_checkpoint', '{"key_info":"verified key context"}'),
                       call('ask_user', '{"question":"Market?","candidates":["A","B"]}')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    with database() as db:
        prompt = db.scalar(select(InputRequestRecord).where(InputRequestRecord.run_id == run.id))
        assert prompt.candidates == ['A', 'B']
        state = db.get(NativeRunStateRecord, run.id).progress
        assert state['state']['key_info'] == 'verified key context'


def test_generator_tools_project_only_public_progress(database):
    principal, tenant, session, run, _ = stack(database, ['generate'])
    def generate(arguments, context):
        yield 'private intermediate'
        return ToolResult('private final')
    def registry(store):
        tools = ToolRegistry()
        tools.register(RegisteredTool(ToolDefinition('generate', 'G', {'type': 'object'}), generate, lambda result: 'public output'))
        return tools
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[call('generate')], [ModelChunk('text', text='done')]]), registry_factory=registry)
    assert run_row(database, run.id).status == 'completed'
    from nexus_platform.runs.service import list_events
    with database() as db:
        events = list_events(db, principal, tenant.id, run.id, 0)
        assert any(e.event_type == 'tool.progress' and e.payload['text'] == 'public output' for e in events)
        assert 'private intermediate' not in str([e.payload for e in events])


def test_approval_resume_does_not_replay_completed_tool(settings_client, database):
    client, _, identity, *_ = settings_client
    principal, tenant, session, run, _ = stack(database, ['echo', 'write'])
    identity[0] = principal
    invoked = []
    async def echo(arguments, context): invoked.append('echo'); return ToolResult('read')
    async def write(arguments, context): invoked.append(arguments['text']); return ToolResult('written')
    def registry(store):
        tools = ToolRegistry()
        tools.register(RegisteredTool(ToolDefinition('echo', 'R', {'type': 'object'}), echo, lambda r: r.data))
        tools.register(RegisteredTool(ToolDefinition('write', 'W', {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']},
            side_effects=True, requires_approval=True), write, lambda r: r.data))
        return tools
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[call('echo'), call('write', '{"text":"original"}')]]), registry_factory=registry)
    assert run_row(database, run.id).status == 'waiting_approval'
    assert invoked == ['echo']
    path = f'/api/v1/tenants/{tenant.id}/native/runs/{run.id}/approvals'
    pending = client.get(path).json()
    assert len(pending) == 1
    response = client.post(path + '/' + pending[0]['id'], json={'approve': True, 'arguments': {'text': 'reviewed'}})
    assert response.status_code == 200, response.text
    resumed = FakeModel([[ModelChunk('text', text='done')]])
    run_once(database, 'worker', model_factory=lambda _: resumed, registry_factory=registry)
    assert run_row(database, run.id).status == 'completed'
    assert invoked == ['echo', 'reviewed']
    with database() as db:
        assert len(list(db.scalars(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run.id)))) == 2
    assert client.post(path + '/' + pending[0]['id'], json={'approve': True}).status_code == 409


def test_preferences_memory_publication_restore_and_steer(settings_client, database):
    client, path, identity, owner, member, tenant_id = settings_client
    root = path.removesuffix('/model-settings') + '/native'
    preferences = client.get(root + '/settings').json()
    preferences['settings']['budgets']['max_rounds'] = 33
    response = client.put(root + '/settings', json={'settings': preferences['settings'], 'expected_version': 0})
    assert response.status_code == 200, response.text
    assert client.put(root + '/settings', json={'settings': preferences['settings'], 'expected_version': 0}).status_code == 409
    identity[0] = member
    assert client.get(root + '/settings').json()['settings']['budgets']['max_rounds'] == 12
    principal, tenant, session, run, _ = stack(database, ['propose_memory_draft'])
    identity[0] = principal
    root = f'/api/v1/tenants/{tenant.id}/native'
    assert client.post(root + f'/runs/{run.id}/steer', json={'content': 'Use only verified evidence'}, headers={'Idempotency-Key': 'steer1'}).status_code == 202
    model = FakeModel([[call('propose_memory_draft', '{"kind":"sop","diff":"Verified reusable method"}')], [ModelChunk('text', text='done')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    assert any(m.content == 'Use only verified evidence' for m in model.requests[0].messages)
    data = client.get(root + '/memory').json()
    assert data['entries'] == [] and len(data['drafts']) == 1
    draft = data['drafts'][0]
    published = client.post(root + '/memory-drafts/' + draft['id'] + '/review', json={'approve': True, 'title': 'Method'})
    assert published.status_code == 200, published.text
    entry = published.json()['id']
    assert client.get(root + '/memory/' + entry).json()['content'] == 'Verified reusable method'
    assert client.post(root + '/memory/' + entry + '/restore', json={'version': 1, 'expected_version': 1}).json()['version'] == 2
    identity[0] = member
    assert client.get(root + '/memory/' + entry).status_code == 404
    identity[0] = principal
    assert client.delete(root + '/memory/' + entry).status_code == 200
    assert client.get(root + '/memory').json()['entries'] == []


def test_model_branch_preserves_source_and_history(settings_client, database):
    client, path, identity, *_ = settings_client
    principal, tenant, session, run, _ = stack(database)
    identity[0] = principal
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[ModelChunk('text', text='original answer')]]))
    with database() as db:
        from nexus_platform.persistence.models import AgentVersionRecord
        target = db.get(AgentVersionRecord, session.agent_version_id).model_profile_version_id
    response = client.post(f'/api/v1/tenants/{tenant.id}/native/sessions/{session.id}/model-branch', json={'model_profile_version_id': str(target)})
    assert response.status_code == 201, response.text
    with database() as db:
        branch = db.get(SessionRecord, UUID(response.json()['id']))
        assert branch.agent_version_id != session.agent_version_id
        assert db.get(SessionRecord, session.id).agent_version_id == session.agent_version_id
        copied = list(db.scalars(select(MessageRecord).where(MessageRecord.session_id == branch.id)))
        assert any(message.content == 'original answer' for message in copied)
        assert all(message.runtime_metadata['source_session_id'] == str(session.id) for message in copied)


def test_protocol_adapters_streaming_and_nonstream():
    async def scenario(protocol, streaming):
        if protocol == 'anthropic_messages':
            events = [ {'type': 'message_start', 'message': {'usage': {'input_tokens': 3}}},
                {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'OK'}},
                {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 2}}, {'type': 'message_stop'}]
            complete = {'content': [{'type': 'text', 'text': 'OK'}], 'stop_reason': 'end_turn', 'usage': {'input_tokens': 3, 'output_tokens': 2}}
        else:
            events = [{'type': 'response.output_text.delta', 'delta': 'OK'}, {'type': 'response.completed', 'response': {'usage': {'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5}}}]
            complete = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}], 'status': 'completed', 'usage': {'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5}}
        async def handler(request):
            payload = json.loads(request.content)
            assert payload['stream'] == streaming
            return httpx.Response(200, text=''.join('data: ' + json.dumps(event) + '\n\n' for event in events), headers={'content-type': 'text/event-stream'}) if streaming else httpx.Response(200, json=complete)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        model = StructuredModel(model='fake', api_key='test', base_url='https://model.example/v1', protocol=protocol, http_client=client, options={'stream': streaming})
        from nexus_core.runtime import ModelRequest
        chunks = [c async for c in model.stream(ModelRequest((ModelMessage('user', 'Hi'),), (), 32))]
        assert ''.join(c.text for c in chunks if c.kind == 'text') == 'OK'
        assert chunks[-1].finish_reason == 'stop'
        assert next(c.total_tokens for c in chunks if c.kind == 'usage') == 5
        await model.close()
    for protocol in ('openai_responses', 'anthropic_messages'):
        for streaming in (True, False): asyncio.run(scenario(protocol, streaming))


def test_retry_and_fallback_never_replay_a_partial_stream():
    async def scenario():
        counts = [0, 0]
        class Bad:
            async def stream(self, request):
                counts[0] += 1
                raise RuntimeFault('model_rate_limited')
                yield
            async def close(self): pass
        class Good:
            async def stream(self, request):
                counts[1] += 1
                yield ModelChunk('text', text='ok')
                yield ModelChunk('done', finish_reason='stop')
            async def close(self): pass
        model = RetryModel(RoutedModel([Bad, Good]), NativePolicy(retry_delay_seconds=0))
        result = [chunk async for chunk in model.stream(None)]
        assert counts == [1, 1] and result[0].text == 'ok'
        class Partial:
            async def stream(self, request):
                yield ModelChunk('text', text='partial')
                raise RuntimeFault('model_provider_unavailable')
            async def close(self): pass
        partial = RetryModel(RoutedModel([Partial, Good]), NativePolicy(retry_delay_seconds=0))
        with pytest.raises(RuntimeFault):
            _ = [chunk async for chunk in partial.stream(None)]
        assert counts[1] == 1
        await model.close(); await partial.close()
    asyncio.run(scenario())
    calls, visible = parse_text_calls('Read <tool_use>{"name":"read","arguments":{"id":"a"}}</tool_use>')
    assert calls[0].name == 'read' and visible == 'Read'


def test_resumed_tools_preserve_checkpoint_and_error_budget():
    """Approval resumption uses the same working state and failure limits as a fresh batch."""
    from nexus_core.runtime import ExecutionBudget
    from nexus_runtimes.native.context.working import WorkingMemory
    from nexus_runtimes.native.engine.recovery import resume_tools

    async def scenario():
        checkpoint = call('update_working_checkpoint', '{"key_info":"resumed evidence"}').tool_call
        failure = call('broken').tool_call
        state = {'pending_calls': [asdict(checkpoint), asdict(failure)]}
        progress = RuntimeProgress(state=state)
        working = WorkingMemory(state, NativePolicy())
        messages, invoked = [], []

        class Gateway:
            async def execute(self, tool_call, token):
                invoked.append(tool_call.name)
                return ToolResult('saved') if tool_call.name == checkpoint.name else ToolResult('failed', error_code='tool_failed')

        async def append(message):
            messages.append(message)

        async def hook(*args):
            pass

        with pytest.raises(RuntimeFault, match='budget_exhausted'):
            await resume_tools(state, Gateway(), CancellationToken(), (), hook, 1, append,
                               progress=progress, budget=ExecutionBudget(max_errors=1), working=working)
        assert working.key_info == state['key_info'] == 'resumed evidence'
        assert progress.errors == 1
        assert state['pending_calls'] == []
        assert invoked == ['update_working_checkpoint', 'broken']
        assert len(messages) == 2

    asyncio.run(scenario())
