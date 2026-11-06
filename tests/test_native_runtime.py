from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_platform import database, create_agent_stack
from nexus_api.main import app
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal, new_id, utc_now
from nexus_core.runtime import ModelChunk, ModelMessage, ModelRequest, RuntimeFault, ToolCall, ToolDefinition, ToolDisposition, ToolResult
from nexus_platform.agents.service import create_agent, publish_agent
from nexus_platform.errors import Conflict
from nexus_platform.models.service import create_model_profile
from nexus_platform.persistence.models import (AuditRecord, InputRequestRecord, MemoryDraftRecord, MessageRecord,
    NativeRunStateRecord, OutboxRecord, RunRecord, ToolInvocationRecord, WorkingCheckpointRecord)
from nexus_platform.runs.execution import prepare_execution, respond_input
from nexus_platform.runs.service import claim_next, create_run, list_events, request_cancel
from nexus_platform.sessions.service import create_session
from nexus_platform.tenants.service import create_tenant
from nexus_platform.authz.resources import grant_resource, register_resource, revoke_resource_grant
from nexus_runtimes.native.models.openai_compatible import OpenAICompatibleModel
from nexus_tools.registry import RegisteredTool, ToolRegistry
from nexus_worker.__main__ import run_once
from nexus_worker.native import DeploymentCredentialResolver


class FakeModel:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.requests = []
        self.closed = False

    async def stream(self, request):
        self.requests.append(request)
        current = next(self.turns)
        if callable(current):
            async for chunk in current():
                yield chunk
            return
        for chunk in current:
            yield chunk
        yield ModelChunk('done', finish_reason='tool_calls' if any(chunk.kind == 'tool_call' for chunk in current) else 'stop')

    async def close(self):
        self.closed = True


def call(name, arguments='{}', id=None):
    return ModelChunk('tool_call', tool_call=ToolCall(id or str(new_id()), name, arguments))


def stack(factory, names=(), budgets=None, shared=False):
    principal = Principal('native-owner', 'test')
    with factory() as db:
        tenant = create_tenant(db, principal, 'Native')
        source = create_tenant(db, principal, 'Tools') if shared else tenant
        with db.begin():
            for name in names:
                register_resource(db, tenant_id=source.id, kind='tool', resource_id=name, version_id='v1')
        grants = []
        if shared:
            for name in names:
                grants.append(grant_resource(db, principal, source_tenant_id=source.id,
                    target_tenant_id=tenant.id, kind='tool', resource_id=name, permissions=['use']))
        _, model = create_model_profile(db, principal, tenant.id, name='model', provider='test', model_name='fake', options={})
        agent = create_agent(db, principal, tenant.id, name='Native', description='', runtime_type='native',
            instructions='Use only authorized tools.', model_profile_version_id=model.id,
            budgets=budgets or {'max_tokens': 100000}, bindings=[{'kind': 'tool', 'resource_id': name,
                'resource_version_id': 'v1', 'source_tenant_id': str(source.id), 'config': {}} for name in names])
        version = publish_agent(db, principal, tenant.id, agent.id)
        session = create_session(db, principal, tenant.id, agent_version_id=version.id)
        run, _ = create_run(db, principal, tenant.id, session.id, message='Hello', idempotency_key='first')
    return principal, tenant, session, run, grants


def run_row(factory, id):
    with factory() as db:
        return db.get(RunRecord, id)


def registry(handler, *, name='echo', side_effects=False, timeout=15):
    result = ToolRegistry()
    result.register(RegisteredTool(ToolDefinition(name, 'Echo', {'type': 'object', 'properties': {
        'text': {'type': 'string'}}, 'required': ['text'], 'additionalProperties': False},
        side_effects=side_effects, timeout_seconds=timeout), handler, lambda result: result.data))
    return result


def test_multitool_bad_arguments_hooks_and_session_history(database):
    principal, tenant, session, run, _ = stack(database, ['echo'])
    invoked = []
    async def echo(args, context):
        invoked.append(args['text'])
        return ToolResult(args['text'])
    model = FakeModel([[call('echo', '{bad'), call('echo', '{"text": 3}'), call('echo', '{"text":"a"}'), call('echo', '{"text":"b"}')],
                       [ModelChunk('text', text='Finished')]])
    phases = []
    async def hook(event):
        phases.append(event.phase)
        if event.phase == 'model.before':
            raise ValueError('private diagnostic')
    assert run_once(database, 'worker', model_factory=lambda _: model,
                    registry_factory=lambda _: registry(echo), hooks=(hook,))
    assert invoked == ['a', 'b']
    assert model.closed
    assert run_row(database, run.id).status == 'completed'
    assert not run_once(database, 'worker', model_factory=lambda _: model)
    assert {'agent.before', 'agent.after', 'turn.before', 'turn.after', 'model.before', 'model.after', 'tool.before', 'tool.after'} <= set(phases)
    with database() as db:
        invocations = list(db.scalars(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run.id).order_by(ToolInvocationRecord.started_at)))
        assert [row.status for row in invocations] == ['failed', 'failed', 'completed', 'completed']
        # '{bad' is cut off (unclosed): refused as truncated, never repaired (tool-call-hardening A).
        assert invocations[0].error_code == 'tool_arguments_truncated'
        assert invocations[1].error_code == 'tool_arguments_invalid'
    with database() as db:
        events = list_events(db, principal, tenant.id, run.id, 0)
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert 'private diagnostic' not in str([event.payload for event in events])
    with database() as db:
        second, _ = create_run(db, principal, tenant.id, session.id, message='Continue', idempotency_key='second')
        second_id = second.id
        # A busy session queues the overlapping submission behind the Runs already admitted.
        overlap, _ = create_run(db, principal, tenant.id, session.id, message='Overlap', idempotency_key='overlap')
        assert overlap.status == 'queued'
        db.rollback()
    next_model = FakeModel([[ModelChunk('text', text='Again')]])
    run_once(database, 'worker', model_factory=lambda _: next_model, registry_factory=lambda _: registry(echo))
    assert any(message.content == 'Finished' for message in next_model.requests[0].messages)
    # Run-scoped replay (P10): earlier Runs' tool exchanges are stored but not replayed to the model.
    assert not any(message.role == 'tool' for message in next_model.requests[0].messages)
    assert run_row(database, second_id).status == 'completed'


def test_waiting_input_checkpoint_and_memory_draft_are_durable(database):
    principal, tenant, session, run, _ = stack(database, ['ask_user', 'update_working_checkpoint', 'propose_memory_draft'])
    model = FakeModel([[call('update_working_checkpoint', '{"content":"remember this task"}'),
                       call('propose_memory_draft', '{"kind":"sop","diff":"proposed only"}'),
                       call('ask_user', '{"question":"Which market?"}')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    assert run_row(database, run.id).status == 'waiting_input'
    with database() as db:
        request = db.scalar(select(InputRequestRecord).where(InputRequestRecord.run_id == run.id))
        assert db.get(WorkingCheckpointRecord, session.id).content == 'remember this task'
        draft = db.scalar(select(MemoryDraftRecord))
        assert draft.status == 'pending_review'
        assert draft.source_run_id == run.id
        assert db.get(NativeRunStateRecord, run.id).progress['turns'] == 1
    with database() as db:
        respond_input(db, principal, tenant.id, run.id, request.id, 'A shares', 'answer-1')
        respond_input(db, principal, tenant.id, run.id, request.id, 'A shares', 'answer-1')
        with pytest.raises(Conflict):
            respond_input(db, principal, tenant.id, run.id, request.id, 'US', 'answer-2')
    resumed = FakeModel([[ModelChunk('text', text='Understood')]])
    run_once(database, 'worker', model_factory=lambda _: resumed)
    assert run_row(database, run.id).status == 'completed'
    assert not run_once(database, 'worker')
    assert 'remember this task' in resumed.requests[0].messages[0].content
    assert 'proposed only' not in resumed.requests[0].messages[0].content
    assert sum(message.content == 'A shares' for message in resumed.requests[0].messages) == 1
    with database() as db:
        assert db.get(NativeRunStateRecord, run.id).progress['turns'] == 2


def test_revoke_grant_between_calls_denies_next_call(database):
    principal, tenant, _, run, grants = stack(database, ['echo'], shared=True)
    seen = []
    async def echo(args, context):
        seen.append(args['text'])
        with database() as db:
            revoke_resource_grant(db, principal, grants[0].id)
        return ToolResult('first result')
    model = FakeModel([[call('echo', '{"text":"first"}'), call('echo', '{"text":"denied"}')], [ModelChunk('text', text='Denied')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: registry(echo))
    assert seen == ['first']
    with database() as db:
        rows = list(db.scalars(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run.id).order_by(ToolInvocationRecord.started_at)))
        assert rows[1].error_code == 'tool_authorization_denied'
        denial = db.scalar(select(AuditRecord).where(AuditRecord.action == 'tool.denied'))
        assert denial.result == 'denied'
    # Context containing now-revoked data must not be sent to another model turn.
    assert run_row(database, run.id).error_code == 'run_authorization_denied'


@pytest.mark.parametrize('side_effects,expected', [(False, 'cancelled'), (True, 'interrupted')])
def test_tool_cancellation_classifies_uncertain_side_effects(database, side_effects, expected):
    principal, tenant, _, run, _ = stack(database, ['echo'])
    async def echo(args, context):
        with database() as db:
            request_cancel(db, principal, tenant.id, run.id)
        await asyncio.sleep(20)
        return ToolResult('should not finish')
    model = FakeModel([[call('echo', '{"text":"go"}')]])
    run_once(database, 'worker', model_factory=lambda _: model,
        registry_factory=lambda _: registry(echo, side_effects=side_effects))
    assert run_row(database, run.id).status == expected
    with database() as db:
        invocation = db.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run.id))
        assert invocation.status == expected
    assert model.closed


def test_active_model_cancellation_closes_stream(database):
    principal, tenant, _, run, _ = stack(database)
    closed = []
    async def stream():
        try:
            yield ModelChunk('text', text='partial')
            with database() as db:
                request_cancel(db, principal, tenant.id, run.id)
            await asyncio.sleep(20)
        finally:
            closed.append(True)
    model = FakeModel([stream])
    run_once(database, 'worker', model_factory=lambda _: model)
    assert run_row(database, run.id).status == 'cancelled'
    assert closed and model.closed


@pytest.mark.parametrize('budgets,turns,code', [
    ({'max_rounds': 1}, [[call('unknown')]], 'budget_exhausted'),
    ({'max_tokens': 1}, [[ModelChunk('text', text='too much')]], 'budget_exhausted'),
])
def test_engine_budgets_end_explicitly(database, budgets, turns, code):
    _, _, _, run, _ = stack(database, budgets=budgets)
    model = FakeModel(turns)
    run_once(database, 'worker', model_factory=lambda _: model)
    assert run_row(database, run.id).error_code == code
    assert model.closed


def test_model_timeout_and_lost_worker_do_not_replay(database):
    _, _, _, run, _ = stack(database, budgets={'model_timeout_seconds': 0.02})
    async def hanging():
        await asyncio.sleep(20)
        yield ModelChunk('text', text='late')
    run_once(database, 'worker', model_factory=lambda _: FakeModel([hanging]))
    assert run_row(database, run.id).error_code == 'model_timeout'
    principal = Principal('other-owner', 'test')
    tenant, _, _, _, _, session = create_agent_stack(database, principal)
    with database() as db:
        recover_run, _ = create_run(db, principal, tenant.id, session.id, message='Recover', idempotency_key='recover')
        task = claim_next(db, 'lost-worker')
    context = prepare_execution(database, task, 'lost-worker')
    with database() as db, db.begin():
        outbox = db.get(OutboxRecord, task)
        outbox.lease_until = utc_now()
        db.add(ToolInvocationRecord(id=new_id(), run_id=recover_run.id, operation_id='side-effect',
            status='running', input_summary={}, output_summary={}, started_at=utc_now()))
    model = FakeModel([])
    run_once(database, 'recovery-worker', model_factory=lambda _: model)
    assert not model.requests
    assert run_row(database, recover_run.id).status == 'interrupted'
    with database() as db:
        assert db.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == context.run_id)).status == 'interrupted'


def test_sse_replay_cursor_input_and_session_isolation(database):
    principal, tenant, session, run, _ = stack(database, ['ask_user'])
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[call('ask_user', '{"question":"Choose"}')]]))
    app.state.session_factory = database
    def override_db():
        with database() as db:
            yield db
    app.dependency_overrides[get_database_session] = override_db
    identity = {'principal': principal}
    app.dependency_overrides[get_principal] = lambda: identity['principal']
    base = f'/api/v1/tenants/{tenant.id}/runs/{run.id}'
    try:
        with TestClient(app) as client:
            pending = client.get(base + '/input').json()
            assert pending['question'] == 'Choose'
            with client.stream('GET', base + '/events', headers={'Accept': 'text/event-stream', 'Last-Event-ID': '2'}) as response:
                assert response.status_code == 200
                text = ''.join(response.iter_text())
            assert 'id: 1\n' not in text
            assert 'event: run.event' in text and 'input.requested' in text
            assert client.get(base + '/events', headers={'Last-Event-ID': 'bad'}).status_code == 422
            body = {'input_request_id': pending['input_request_id'], 'response': 'yes'}
            assert client.post(base + '/input', json=body, headers={'Idempotency-Key': 'respond'}).status_code == 202
            assert client.post(base + '/input', json=body, headers={'Idempotency-Key': 'respond'}).status_code == 202
            history_url = f'/api/v1/tenants/{tenant.id}/sessions/{session.id}/messages'
            assert sum(row['content'] == 'yes' for row in client.get(history_url).json()['messages']) == 1
            identity['principal'] = Principal('stranger', 'test')
            assert client.get(base + '/events', headers={'Accept': 'text/event-stream'}).status_code == 404
            assert client.get(history_url).status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


def test_provider_fragmented_calls_usage_and_error_redaction():
    async def verify():
        requests = []
        def transport(request):
            requests.append(json.loads(request.content))
            chunks = [
                {'choices': [{'delta': {'content': 'Hi'}, 'index': 0, 'finish_reason': None}]},
                {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call_1', 'type': 'function',
                    'function': {'name': 'echo', 'arguments': '{"text":'}}]}, 'index': 0, 'finish_reason': None}]},
                {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '"ok"}'}}]},
                    'index': 0, 'finish_reason': 'tool_calls'}]},
                {'choices': [], 'usage': {'prompt_tokens': 4, 'completion_tokens': 3, 'total_tokens': 7}},
            ]
            body = ''.join('data: ' + json.dumps({'id': 'stream', 'object': 'chat.completion.chunk',
                'created': 1, 'model': 'fake', **chunk}) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n'
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=body)
        model = OpenAICompatibleModel(model='fake', api_key='private-value', http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        request = ModelRequest((ModelMessage('user', 'Hello'),), (), 100)
        chunks = [chunk async for chunk in model.stream(request)]
        assert [chunk.tool_call for chunk in chunks if chunk.kind == 'tool_call'] == [ToolCall('call_1', 'echo', '{"text":"ok"}')]
        assert any(chunk.total_tokens == 7 for chunk in chunks)
        assert chunks[-1].finish_reason == 'tool_calls'
        await model.close()
        def broken(request):
            return httpx.Response(429, json={'error': {'message': 'private-value', 'type': 'rate_limit', 'code': 'rate_limit'}})
        model = OpenAICompatibleModel(model='fake', api_key='private-value', http_client=httpx.AsyncClient(transport=httpx.MockTransport(broken)))
        with pytest.raises(RuntimeFault) as error:
            _ = [chunk async for chunk in model.stream(request)]
        assert str(error.value) == 'model_rate_limited'
        assert 'private-value' not in str(error.value)
        await model.close()
    asyncio.run(verify())


def test_environment_credentials_are_allowlisted_and_not_repr(deployment_config):
    from nexus_core.platform import CredentialRef
    deployment_config('')
    reference = CredentialRef(new_id(), 'environment', 'env://MODEL_TEST_KEY', 'tenant')
    resolver = DeploymentCredentialResolver()
    with pytest.raises(RuntimeFault):
        resolver.resolve(reference, principal_id=new_id(), run_id=new_id())
    deployment_config('[model_credentials]\nMODEL_TEST_KEY = "private-value"\n')
    lease = resolver.resolve(reference, principal_id=new_id(), run_id=new_id())
    assert 'private-value' not in repr(lease)
    assert lease.reveal_for_call() == 'private-value'


def test_context_compaction_preserves_tool_exchanges_and_original_messages(database):
    from nexus_runtimes.native.context import compact_history, resolve_incomplete_exchanges
    original = (ModelMessage('system', 'Rules'), ModelMessage('user', 'a' * 2000),
        ModelMessage('assistant', 'b' * 2000), ModelMessage('user', 'Current question'),
        ModelMessage('assistant', '', (ToolCall('one', 'echo', '{}'),)),
        ModelMessage('tool', 'result', tool_call_id='one'))
    compacted, removed = compact_history(original, 1000)
    assert removed == 2
    assert compacted[-3:] == original[-3:]
    assert 'partial' in compacted[1].content
    assert len(original[1].content) == 2000
    incomplete = resolve_incomplete_exchanges((original[-2], ModelMessage('user', 'Continue after crash')))
    assert incomplete[1].role == 'tool'
    assert incomplete[1].tool_call_id == 'one'
    assert 'unknown' in incomplete[1].content
    principal, tenant, session, run, _ = stack(database)
    other_session = None
    with database() as db:
        other_session = create_session(db, principal, tenant.id, agent_version_id=session.agent_version_id)
        from nexus_platform.runs.execution import add_message
        with db.begin():
            db.add(MessageRecord(id=new_id(), session_id=other_session.id, sequence=1, role='user',
                                 content='foreign session private text', runtime_metadata={}, created_at=utc_now()))
    model = FakeModel([[ModelChunk('text', text='Safe')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    assert 'foreign session private text' not in str(model.requests)


def test_tool_timeout_exit_and_continuation_protocol(database):
    principal, tenant, session, run, _ = stack(database, ['echo'])
    async def slow(args, context):
        await asyncio.sleep(20)
        return ToolResult('late')
    model = FakeModel([[call('echo', '{"text":"go"}')], [ModelChunk('text', text='timeout handled')]])
    run_once(database, 'worker', model_factory=lambda _: model,
             registry_factory=lambda _: registry(slow, timeout=0.02))
    assert run_row(database, run.id).status == 'completed'
    with database() as db:
        assert db.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run.id)).error_code == 'tool_timeout'
    with database() as db:
        second, _ = create_run(db, principal, tenant.id, session.id, message='Next', idempotency_key='next')
    async def continuing(args, context):
        return ToolResult('ok', continuation='Continue with evidence')
    model = FakeModel([[call('echo', '{"text":"a"}'), call('echo', '{"text":"b"}')], [ModelChunk('text', text='complete')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: registry(continuing))
    roles = [message.role for message in model.requests[1].messages]
    assert roles[-4:] == ['assistant', 'tool', 'tool', 'user']
    with database() as db:
        third, _ = create_run(db, principal, tenant.id, session.id, message='Exit', idempotency_key='exit')
    async def exit_tool(args, context):
        return ToolResult('explicit failure', disposition=ToolDisposition.EXIT, exit_status='failed', error_code='explicit_exit')
    model = FakeModel([[call('echo', '{"text":"go"}')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: registry(exit_tool))
    assert run_row(database, third.id).status == 'failed'
    assert run_row(database, third.id).error_code == 'explicit_exit'


def test_waiting_cancel_and_unbound_tools_cannot_execute(database):
    principal, tenant, _, run, _ = stack(database, ['ask_user'])
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[call('ask_user', '{"question":"Proceed?"}')]]))
    with database() as db:
        pending = db.scalar(select(InputRequestRecord).where(InputRequestRecord.run_id == run.id))
    with database() as db:
        request_cancel(db, principal, tenant.id, run.id)
        with pytest.raises(Conflict):
            respond_input(db, principal, tenant.id, run.id, pending.id, 'yes', 'answer')
    assert run_row(database, run.id).status == 'cancelled'
    assert not run_once(database, 'worker')
    _, _, _, second, _ = stack(database, [])
    seen = []
    async def forbidden(args, context):
        seen.append(True)
        return ToolResult('forbidden')
    model = FakeModel([[call('echo', '{"text":"go"}')], [ModelChunk('text', text='No access')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: registry(forbidden))
    assert not seen
    with database() as db:
        assert db.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == second.id)).error_code == 'tool_not_registered'


def test_duration_budget_and_incomplete_provider_stream(database):
    _, _, _, run, _ = stack(database, ['echo'], budgets={'max_seconds': 0.03})
    async def slow(args, context):
        await asyncio.sleep(20)
        return ToolResult('late')
    run_once(database, 'worker', model_factory=lambda _: FakeModel([[call('echo', '{"text":"go"}')]]),
             registry_factory=lambda _: registry(slow))
    assert run_row(database, run.id).error_code == 'budget_exhausted'
    _, _, _, second, _ = stack(database)
    async def broken_stream():
        yield ModelChunk('text', text='incomplete')
    model = FakeModel([broken_stream])
    run_once(database, 'worker', model_factory=lambda _: model)
    assert run_row(database, second.id).error_code == 'model_stream_invalid'
    assert model.closed


@pytest.mark.parametrize('failure,expected', [('timeout', 'model_timeout'), ('invalid', 'model_stream_invalid'), ('context', 'model_context_exceeded')])
def test_provider_deadline_invalid_stream_and_context_errors(failure, expected):
    async def verify():
        def transport(request):
            if failure == 'timeout':
                raise httpx.ReadTimeout('private-value', request=request)
            if failure == 'context':
                return httpx.Response(400, json={'error': {'message': 'private-value', 'type': 'invalid_request_error', 'code': 'context_length_exceeded'}})
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content='data: [DONE]\n\n')
        model = OpenAICompatibleModel(model='fake', api_key='private-value', http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        with pytest.raises(RuntimeFault) as error:
            _ = [chunk async for chunk in model.stream(ModelRequest((ModelMessage('user', 'hello'),), (), 100))]
        assert error.value.code == expected
        assert 'private-value' not in str(error.value)
        await model.close()
    asyncio.run(verify())


def test_unverified_sandbox_capability_is_not_executable(database):
    _, _, _, run, _ = stack(database, ['code_run'])
    seen = []
    async def forbidden(args, context):
        seen.append(True)
        return ToolResult('must not execute')
    tools = ToolRegistry()
    tools.register(RegisteredTool(ToolDefinition('code_run', 'Code', {'type': 'object'}, capability='sandbox_code'), forbidden))
    model = FakeModel([[call('code_run')], [ModelChunk('text', text='Sandbox unavailable')]])
    run_once(database, 'worker', model_factory=lambda _: model, registry_factory=lambda _: tools)
    assert model.requests[0].tools == ()
    assert not seen
    with database() as db:
        assert db.scalar(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id == run.id)).error_code == 'sandbox_unavailable'
