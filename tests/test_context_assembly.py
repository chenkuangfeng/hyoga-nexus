"""Context assembly contracts: deterministic input, live permissions and transaction isolation."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select

from nexus_core.platform import utc_now
from nexus_core.runtime import ModelChunk, ModelMessage, RuntimeFault, ToolCall, ToolDefinition, ToolResult
from nexus_core.runtime.context import ContextBlock, ContextBuildInput, ContextDependency
from nexus_core.runtime.context_assembly import RequestContextAssembler
from nexus_platform.memory import providers
from nexus_platform.persistence.models import MemoryEntryRecord, OutboxRecord, RunRecord, SessionMemorySnapshotRecord
from nexus_platform.runs.context_access import require_context_access
from nexus_platform.runs.preparation import ContextPreparationService, ExecutionPreparer
from nexus_platform.runs.service import claim_next, create_run
from nexus_platform.sessions.projection_cache import ProjectionCache
from nexus_runtimes.native.context.providers import ContextProviderRegistry, ProviderRegistration
from nexus_runtimes.native.models.retry import RetryModel
from nexus_core.native import NativePolicy
from nexus_tools.gateway import AuthorizedToolGateway
from nexus_tools.registry import RegisteredTool, ToolRegistry
from nexus_worker.__main__ import run_once

from test_platform import database  # noqa: F401
from test_native_runtime import FakeModel, stack, run_row
from test_memory_snapshot import _publish, _index
from test_memory_evolution_stage6 import FakeProvider, _choose


def block(key, text, **kwargs):
    return ContextBlock(key, 'test', 'user', 'turn_tail', 10, text, **kwargs)


def test_assembly_is_deterministic_and_keeps_complete_tool_exchange():
    history = (ModelMessage('user', 'task'),
               ModelMessage('assistant', '', (ToolCall('c', 'read', '{}'),)),
               ModelMessage('tool', 'data', tool_call_id='c'))
    blocks = (ContextBlock('agent', 'agent', 'system', 'system_static', 0, 'rules'), block('z', 'last'), block('a', 'first'))
    assembler = RequestContextAssembler()
    a = assembler.assemble(blocks, history, layout='v2')
    b = assembler.assemble(tuple(reversed(blocks)), history, layout='v2')
    assert a == b
    assert a.messages[2:4] == history[1:]
    assert 'first' in a.messages[-2].content and 'last' in a.messages[-1].content
    assert 'not a new user request' in a.messages[-1].content
    assert history[-1].content == 'data'


def test_duplicate_blocks_and_pending_exchange_are_rejected():
    assembler = RequestContextAssembler()
    with pytest.raises(RuntimeFault, match='context_configuration_invalid'):
        assembler.assemble((block('x', 'one'), block('x', 'two')), ())
    with pytest.raises(RuntimeFault, match='context_exchange_incomplete'):
        assembler.assemble((block('x', 'one'),),
            (ModelMessage('assistant', '', (ToolCall('pending', 'read', '{}'),)),))


def test_cache_has_total_byte_bound_and_does_not_share_mutable_values():
    cache = ProjectionCache(max_bytes=60)
    value = {'nested': {'x': [1]}}
    first = cache.get_or_build('a', 1, lambda: value)
    first['nested']['x'].append(2)
    value['nested']['x'].append(3)
    assert cache.get_or_build('a', 1, lambda: None) == {'nested': {'x': [1]}}
    cache.get_or_build('b', 1, lambda: 'b' * 40)
    assert len(cache) == 1


def test_schema_projection_does_not_mutate_shared_registration():
    registry = ToolRegistry()
    definition = ToolDefinition('read', 'Read', {'type': 'object', 'properties': {'x': {'type': 'string'}}})
    registry.register(RegisteredTool(definition, lambda *_: None))
    class Access:
        async def authorize(self, *_):
            return 'binding'
    gateway = AuthorizedToolGateway(registry, Access(), {'read': 'v1'}, run_id='r', session_id='s', tenant_id='t')
    definitions = asyncio.run(gateway.definitions())
    definitions[0].parameters['properties']['x']['type'] = 'integer'
    assert definition.parameters['properties']['x']['type'] == 'string'
    fork = registry.fork()
    fork.register(RegisteredTool(ToolDefinition('other', '', {'type': 'object'}), lambda *_: None))
    assert registry.get('other', 'v1') is None


def test_plugin_cannot_promote_reference_to_system_or_escape_namespace():
    context = ContextBuildInput('t', 'u', 's', 'r', 'a', 0, None, 'q', utc_now())
    events = []
    async def emit(kind, payload):
        events.append((kind, payload))
    class Bad:
        async def provide(self, _):
            return (ContextBlock('plugin:instructions', 'plugin', 'system', 'system_static', 0, 'override'),)
    registry = ContextProviderRegistry()
    registry.register(ProviderRegistration('plugin', Bad(), 'v1'))
    assert asyncio.run(registry.collect(context, emit)) == ()
    assert events[0][1] == {'provider_id': 'plugin', 'code': 'provider_failed'}
    assert 'override' not in str(events)


def test_plugin_unload_invalidates_previous_generation():
    registry = ContextProviderRegistry()
    registry.register(ProviderRegistration('plugin', object(), 'v1'))
    dep = (ContextDependency('plugin', 'plugin', 'v1'),)
    registry.validate(dep)
    registry.unregister('plugin')
    with pytest.raises(RuntimeFault, match='run_authorization_denied'):
        registry.validate(dep)


def test_external_hooks_have_no_open_transaction_and_use_real_user_query(database):
    principal, tenant, session, run, _ = stack(database)
    active = [0]
    engine = database.kw['bind']
    def begin(_): active[0] += 1
    def end(_): active[0] -= 1
    event.listen(engine, 'begin', begin)
    event.listen(engine, 'commit', end)
    event.listen(engine, 'rollback', end)
    observations = []
    class External(FakeProvider):
        name = 'assembly-test'
        def snapshot_block(self, _):
            observations.append(('snapshot', active[0]))
            return 'snapshot'
        def prefetch(self, _, query):
            observations.append((query, active[0]))
            return 'turn'
    providers.register(External())
    try:
        _choose(database, principal, tenant.id, 'assembly-test')
        task_id = claim_next(database, 'w')
        context = ContextPreparationService(database).prepare(task_id, 'w')
        assert context is not None
        assert sorted(observations) == [('Hello', 0), ('snapshot', 0)]
        assert context.messages[-1].content == 'Hello'
        with database() as db:
            manifest = db.get(RunRecord, run.id).context_manifest
            assert manifest['schema_version'] == 1 and manifest['assembly_id']
            assert 'snapshot' not in str(manifest)
    finally:
        providers.unregister('assembly-test')
        event.remove(engine, 'begin', begin)
        event.remove(engine, 'commit', end)
        event.remove(engine, 'rollback', end)


@pytest.mark.parametrize('change', ['cancel', 'lease'])
def test_finalization_rejects_cancelled_or_stale_preparation(database, change):
    _, _, _, run, _ = stack(database)
    task_id = claim_next(database, 'w')
    draft = ExecutionPreparer(database).prepare(task_id, 'w', defer=True)
    with database() as db, db.begin():
        if change == 'cancel':
            db.get(RunRecord, run.id).cancel_requested_at = utc_now()
        else:
            db.get(OutboxRecord, task_id).lease_owner = 'new-worker'
    result, changed = ContextPreparationService(database).finalize(draft, {}, task_id, 'w')
    assert result is None and changed is False
    assert run_row(database, run.id).status == ('cancelled' if change == 'cancel' else 'queued')


def test_deleted_memory_rebuilds_session_snapshot_and_hides_tainted_history(database):
    principal, tenant, session, run, _ = stack(database)
    _publish(database, run, 'private fact', 'secret')
    first = FakeModel([[ModelChunk('text', text='answer using secret')]])
    run_once(database, 'w', model_factory=lambda _: first)
    assert 'private fact' in first.requests[0].messages[0].content
    with database() as db, db.begin():
        entry = db.scalar(select(MemoryEntryRecord))
        entry.active = False
    with database() as db:
        second, _ = create_run(db, principal, tenant.id, session.id, message='next', idempotency_key='next')
    later = FakeModel([[ModelChunk('text', text='safe')]])
    run_once(database, 'w', model_factory=lambda _: later)
    sent = str(later.requests[0].messages)
    assert 'private fact' not in sent and 'answer using secret' not in sent
    assert run_row(database, second.id).status == 'completed'


@pytest.mark.parametrize('mutation', ['enabled', 'active', 'expired', 'owner', 'tenant'])
def test_each_attempt_rechecks_frozen_memory(database, mutation):
    _, _, session, run, _ = stack(database)
    _publish(database, run, 'private fact', 'secret')
    task_id = claim_next(database, 'w')
    assert ContextPreparationService(database).prepare(task_id, 'w')
    with database() as db, db.begin():
        entry = db.scalar(select(MemoryEntryRecord))
        if mutation == 'expired': entry.valid_until = utc_now() - timedelta(seconds=1)
        elif mutation == 'owner': entry.owner_user_id = uuid4()
        elif mutation == 'tenant': entry.tenant_id = uuid4()
        else: setattr(entry, mutation, False)
        # owner mutation uses no FK write; evaluate the guarded in-transaction view.
        with pytest.raises(RuntimeFault, match='run_authorization_denied'):
            require_context_access(db, db.get(RunRecord, run.id), (run.id,))
        db.rollback()


def test_retry_does_not_send_old_context_after_memory_revocation(database):
    _, _, _, run, _ = stack(database)
    _publish(database, run, 'private fact', 'secret')
    class Transient:
        def __init__(self): self.calls = 0
        async def stream(self, request):
            self.calls += 1
            with database() as db, db.begin():
                db.scalar(select(MemoryEntryRecord)).enabled = False
            raise RuntimeFault('model_rate_limited')
            yield  # async generator protocol
        async def close(self): pass
    inner = Transient()
    model = RetryModel(inner, NativePolicy(retry_delay_seconds=0))
    run_once(database, 'w', model_factory=lambda _: model)
    assert inner.calls == 1
    assert run_row(database, run.id).error_code == 'run_authorization_denied'


def test_legacy_snapshot_is_rebuilt_instead_of_injecting_unattributed_text(database):
    _, _, session, run, _ = stack(database)
    _index(database, run, session.id)
    with database() as db, db.begin():
        row = db.get(SessionMemorySnapshotRecord, session.id)
        row.context_dependencies = None
        row.index_text = 'legacy secret without a source'
    model = FakeModel([[ModelChunk('text', text='ok')]])
    run_once(database, 'w', model_factory=lambda _: model)
    assert 'legacy secret' not in str(model.requests[0].messages)


def test_provider_lifetimes_reuse_session_bytes_and_refresh_step_material(database):
    from nexus_platform.runs.context_plugins import unregister_plugin_generation
    counts = {'session': 0, 'run': 0, 'step': 0}
    class Plugin:
        def __init__(self, lifetime): self.lifetime = lifetime
        async def provide(self, context):
            counts[self.lifetime] += 1
            return (block(f'{self.lifetime}:note', f'{self.lifetime}-material-{counts[self.lifetime]}'),)
    registrations = tuple(ProviderRegistration(name, Plugin(name), 'test-v1', lifetime=name) for name in counts)
    principal, tenant, session, run, _ = stack(database)
    try:
        first = FakeModel([[ModelChunk('text', text='one')]])
        run_once(database, 'w', model_factory=lambda _: first, context_providers=registrations)
        assert run_row(database, run.id).status == 'completed'
        with database() as db:
            second, _ = create_run(db, principal, tenant.id, session.id, message='next', idempotency_key='next')
        later = FakeModel([[ModelChunk('text', text='two')]])
        run_once(database, 'w', model_factory=lambda _: later, context_providers=registrations)
        assert run_row(database, second.id).status == 'completed'
        assert counts == {'session': 1, 'run': 2, 'step': 2}
        assert 'session-material-1' in str(later.requests[0].messages)
        assert 'run-material-2' in str(later.requests[0].messages)
        assert 'step-material-2' in str(later.requests[0].messages)
    finally:
        for name in counts: unregister_plugin_generation(name)


def test_provider_run_snapshot_survives_wait_resume(database):
    from nexus_platform.runs.context_plugins import unregister_plugin_generation
    from nexus_platform.persistence.models import InputRequestRecord
    from nexus_platform.runs.execution import respond_input
    from test_native_runtime import call
    count = [0]
    class Plugin:
        async def provide(self, context):
            count[0] += 1
            return (block('durable:note', 'frozen run material'),)
    registration = ProviderRegistration('durable', Plugin(), 'test-v1')
    principal, tenant, session, run, _ = stack(database, ['ask_user'])
    try:
        first = FakeModel([[call('ask_user', '{"question":"Choose"}')]])
        run_once(database, 'w', model_factory=lambda _: first, context_providers=(registration,))
        assert run_row(database, run.id).status == 'waiting_input'
        with database() as db:
            request = db.scalar(select(InputRequestRecord).where(InputRequestRecord.run_id == run.id))
            request_id = request.id
        with database() as db:
            respond_input(db, principal, tenant.id, run.id, request_id, 'yes', 'answer')
        second = FakeModel([[ModelChunk('text', text='done')]])
        run_once(database, 'w', model_factory=lambda _: second, context_providers=(registration,))
        assert run_row(database, run.id).status == 'completed'
        assert count == [1]
        assert 'frozen run material' in str(second.requests[0].messages)
    finally:
        unregister_plugin_generation('durable')


def test_restarted_provider_generation_cannot_reuse_old_content(database):
    from nexus_platform.runs.context_plugins import register_plugin_generation, unregister_plugin_generation
    from nexus_platform.runs.context_access import merge_dependencies
    _, _, _, run, _ = stack(database)
    task_id = claim_next(database, 'w')
    context = ContextPreparationService(database).prepare(task_id, 'w')
    register_plugin_generation('versioned', 'new')
    try:
        with database() as db, db.begin():
            row = db.get(RunRecord, run.id)
            merge_dependencies(row, (ContextDependency('plugin', 'versioned', 'old'),))
            with pytest.raises(RuntimeFault, match='run_authorization_denied'):
                require_context_access(db, row)
    finally:
        unregister_plugin_generation('versioned')


def test_optional_plugin_group_timeout_skips_without_failing_run(monkeypatch):
    import nexus_runtimes.native.context.providers as module
    monkeypatch.setattr(module, 'GROUP_TIMEOUT', 0.02)
    events = []
    class Slow:
        async def provide(self, _):
            await asyncio.sleep(10)
    async def emit(kind, payload): events.append((kind, payload))
    registry = ContextProviderRegistry()
    registry.register(ProviderRegistration('slow', Slow(), 'v1'))
    context = ContextBuildInput('t', 'u', 's', 'r', 'a', 0, None, 'q', utc_now())
    assert asyncio.run(registry.collect(context, emit)) == ()
    assert events == [('context.provider_failed', {'provider_id': 'slow', 'code': 'provider_timeout'})]


def test_synchronous_provider_capacity_is_held_until_timed_out_work_really_ends(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import BoundedSemaphore
    release = Event()
    pool = ThreadPoolExecutor(max_workers=4)
    capacity = BoundedSemaphore(4)
    monkeypatch.setattr(providers, '_POOL', pool)
    monkeypatch.setattr(providers, '_CAPACITY', capacity)
    class Slow:
        name = 'capacity-test'
        def prefetch(self, *_): release.wait(); return 'late'
        def snapshot_block(self, *_): release.wait(); return 'late'
    provider = Slow()
    providers.register(provider)
    try:
        arguments = dict(tenant_id=uuid4(), owner_id=uuid4(), session_id=uuid4(), query='q', snapshot=True, timeout=0.01)
        first = providers.collect_context(provider, **arguments)
        second = providers.collect_context(provider, **arguments)
        third = providers.collect_context(provider, **arguments)
        assert first['prefetch'] == second['prefetch'] == ''
        assert third['prefetch_error'] == 'provider_capacity_exceeded'
        assert third['snapshot_block_error'] == 'provider_capacity_exceeded'
        assert provider.name not in providers._PAUSED_UNTIL  # backpressure is not a provider failure
        assert not capacity.acquire(blocking=False)
    finally:
        release.set()
        pool.shutdown(wait=True)
        providers.unregister(provider.name)
    assert all(capacity.acquire(blocking=False) for _ in range(4))


def test_plugin_collection_is_bounded_and_keeps_registration_independent_order():
    active, peak = [0], [0]
    class Plugin:
        def __init__(self, name): self.name = name
        async def provide(self, _):
            active[0] += 1
            peak[0] = max(active[0], peak[0])
            await asyncio.sleep(0.001)
            active[0] -= 1
            return (block(self.name + ':note', 'data'),)
    registry = ContextProviderRegistry()
    for i in range(9):
        name = f'provider{i}'
        registry.register(ProviderRegistration(name, Plugin(name), 'v1'))
    async def emit(*_): pass
    context = ContextBuildInput('t', 'u', 's', 'r', 'a', 0, None, 'q', utc_now())
    blocks = asyncio.run(registry.collect(context, emit))
    assert peak[0] == 4 and len(blocks) == 9
    assert all(b.key.startswith('plugin:') and b.text.startswith('[Plugin reference:') for b in blocks)


def test_unattributed_legacy_run_is_hidden_without_losing_new_user_message(database):
    principal, tenant, session, run, _ = stack(database)
    run_once(database, 'w', model_factory=lambda _: FakeModel([[ModelChunk('text', text='old private fact')]]))
    with database() as db, db.begin():
        db.get(RunRecord, run.id).context_manifest = {'schema_version': 0, 'dependencies': []}
    with database() as db:
        second, _ = create_run(db, principal, tenant.id, session.id, message='new question', idempotency_key='new')
    model = FakeModel([[ModelChunk('text', text='new answer')]])
    run_once(database, 'w', model_factory=lambda _: model)
    assert run_row(database, second.id).status == 'completed'
    assert 'old private fact' not in str(model.requests[0].messages)
    assert 'new question' in str(model.requests[0].messages)


def test_application_revocation_prevents_even_the_next_provider_callback():
    invoked = []
    class Plugin:
        async def provide(self, _):
            invoked.append(True)
            return (block('revoked:note', 'data'),)
    registry = ContextProviderRegistry(generation_check=lambda _: False)
    registry.register(ProviderRegistration('revoked', Plugin(), 'v1'))
    context = ContextBuildInput('t', 'u', 's', 'r', 'a', 0, None, 'q', utc_now())
    async def emit(*_): pass
    with pytest.raises(RuntimeFault, match='run_authorization_denied'):
        asyncio.run(registry.collect(context, emit))
    assert invoked == []


def test_wait_resume_rejects_a_changed_tool_schema_before_sending_model(database):
    from nexus_platform.persistence.models import InputRequestRecord
    from nexus_platform.runs.execution import respond_input
    from nexus_tools.builtins import builtins
    from test_native_runtime import call
    principal, tenant, session, run, _ = stack(database, ['ask_user'])
    first = FakeModel([[call('ask_user', '{"question":"Choose"}')]])
    run_once(database, 'w', model_factory=lambda _: first)
    with database() as db:
        request = db.scalar(select(InputRequestRecord).where(InputRequestRecord.run_id == run.id))
        request_id = request.id
    with database() as db:
        respond_input(db, principal, tenant.id, run.id, request_id, 'yes', 'answer')
    altered = ToolRegistry()
    for definition in builtins().definitions():
        registered = builtins().get(definition.name, definition.version)
        if definition.name == 'ask_user':
            registered = replace(registered, definition=replace(definition, description='Changed schema description'))
        altered.register(registered)
    later = FakeModel([[ModelChunk('text', text='must not be sent')]])
    run_once(database, 'w', model_factory=lambda _: later, registry_factory=lambda _: altered)
    assert later.requests == []
    assert run_row(database, run.id).error_code == 'context_prefix_changed'


def test_new_plugin_generation_rebuilds_session_content_for_new_run(database):
    from nexus_platform.runs.context_plugins import unregister_plugin_generation
    principal, tenant, session, run, _ = stack(database)
    class Plugin:
        def __init__(self, text): self.text = text
        async def provide(self, _): return (block('changing:note', self.text),)
    old = ProviderRegistration('changing', Plugin('old generation material'), 'v1', lifetime='session')
    new = ProviderRegistration('changing', Plugin('new generation material'), 'v2', lifetime='session')
    try:
        run_once(database, 'w', model_factory=lambda _: FakeModel([[ModelChunk('text', text='old answer')]]),
                 context_providers=(old,))
        with database() as db:
            next_run, _ = create_run(db, principal, tenant.id, session.id, message='next', idempotency_key='next')
        model = FakeModel([[ModelChunk('text', text='new answer')]])
        run_once(database, 'w', model_factory=lambda _: model, context_providers=(new,))
        assert run_row(database, next_run.id).status == 'completed'
        assert 'new generation material' in str(model.requests[0].messages)
        assert 'old generation material' not in str(model.requests[0].messages)
        assert 'old answer' not in str(model.requests[0].messages)
    finally:
        unregister_plugin_generation('changing')


def test_external_memory_provider_can_pin_a_stable_restart_generation():
    provider = SimpleNamespace(name='stable-provider')
    try:
        providers.register(provider, generation='backend-v1')
        assert providers.generation(provider.name) == 'backend-v1'
        providers.unregister(provider.name)
        providers.register(SimpleNamespace(name=provider.name), generation='backend-v1')
        assert providers.generation(provider.name) == 'backend-v1'
    finally:
        providers.unregister(provider.name)


def test_tool_schema_property_order_is_canonical_across_registration_instances():
    class Access:
        async def authorize(self, *_): return 'binding'
    def definitions(properties):
        registry = ToolRegistry()
        registry.register(RegisteredTool(ToolDefinition('read', '', {'type': 'object', 'properties': properties}), lambda *_: None))
        gateway = AuthorizedToolGateway(registry, Access(), {'read': 'v1'}, run_id='r', session_id='s', tenant_id='t')
        return asyncio.run(gateway.definitions())
    first = definitions({'z': {'type': 'string'}, 'a': {'type': 'integer'}})
    second = definitions({'a': {'type': 'integer'}, 'z': {'type': 'string'}})
    assert str(first) == str(second)
    assert list(first[0].parameters['properties']) == ['a', 'z']


def test_model_branch_keeps_source_messages_and_inherits_tool_read_dependencies(database):
    from nexus_platform.persistence.models import AgentVersionRecord, SessionRecord
    from nexus_platform.sessions.fork import fork
    from test_native_runtime import call
    principal, tenant, session, run, _ = stack(database, ['read_memory'])
    _publish(database, run, 'sensitive item', 'sensitive body')
    with database() as db, db.begin():
        entry = db.scalar(select(MemoryEntryRecord))
        entry.project = 'source-only'  # excluded from the default project's index; explicitly read by id
        entry_id = entry.id
    first = FakeModel([[call('read_memory', '{"entry_id":"' + str(entry_id) + '"}')],
                       [ModelChunk('text', text='ORIGINAL-SENSITIVE ANSWER')]])
    run_once(database, 'w', model_factory=lambda _: first)
    assert run_row(database, run.id).status == 'completed'
    with database() as db:
        version = db.get(AgentVersionRecord, session.agent_version_id)
        target_model_id = version.model_profile_version_id
    with database() as db:
        branch = fork(db, principal, tenant.id, session.id, target_model_id)
    with database() as db:
        next_run, _ = create_run(db, principal, tenant.id, UUID(branch['id']), message='followup', idempotency_key='branch')
    model = FakeModel([[ModelChunk('text', text='branch answer')]])
    run_once(database, 'w', model_factory=lambda _: model)
    assert run_row(database, next_run.id).status == 'completed'
    assert 'ORIGINAL-SENSITIVE ANSWER' in str(model.requests[0].messages)
    with database() as db:
        manifest = db.get(RunRecord, next_run.id).context_manifest
        assert any(d['kind'] == 'memory' and d['resource_id'] == str(entry_id) for d in manifest['dependencies'])
    with database() as db, db.begin():
        db.get(MemoryEntryRecord, entry_id).enabled = False
    with database() as db:
        last, _ = create_run(db, principal, tenant.id, UUID(branch['id']), message='after revoke', idempotency_key='last')
    safe = FakeModel([[ModelChunk('text', text='safe')]])
    run_once(database, 'w', model_factory=lambda _: safe)
    assert run_row(database, last.id).status == 'completed'
    sent = str(safe.requests[0].messages)
    assert 'ORIGINAL-SENSITIVE ANSWER' not in sent and 'branch answer' not in sent


def test_history_tool_result_retains_the_original_runs_resource_permissions(database):
    from nexus_platform.agents.service import create_agent, publish_agent
    from nexus_platform.sessions.service import create_session
    from nexus_platform.authz.resources import register_resource, revoke_resource_grant
    from nexus_platform.persistence.models import AgentVersionRecord
    from test_native_runtime import call
    principal, tenant, source_session, source_run, grants = stack(database, ['echo'], shared=True)
    run_once(database, 'w', model_factory=lambda _: FakeModel([[ModelChunk('text', text='ORIGINAL SHARED ANSWER')]]))
    with database() as db:
        version = db.get(AgentVersionRecord, source_session.agent_version_id)
        model_id = version.model_profile_version_id
    with database() as db, db.begin():
        register_resource(db, tenant_id=tenant.id, kind='tool', resource_id='read_conversation', version_id='v1')
    with database() as db:
        agent = create_agent(db, principal, tenant.id, name='Reader', description='', runtime_type='native',
            instructions='Read authorized history.', model_profile_version_id=model_id, budgets={},
            bindings=[{'kind': 'tool', 'resource_id': 'read_conversation', 'resource_version_id': 'v1',
                       'source_tenant_id': str(tenant.id), 'config': {}}])
        version = publish_agent(db, principal, tenant.id, agent.id)
        session = create_session(db, principal, tenant.id, agent_version_id=version.id)
        reader, _ = create_run(db, principal, tenant.id, session.id, message='read earlier', idempotency_key='reader')
    arguments = '{"session_id":"' + str(source_session.id) + '","sequence":2,"before":0,"after":0}'
    model = FakeModel([[call('read_conversation', arguments)], [ModelChunk('text', text='DERIVED ANSWER')]])
    run_once(database, 'w', model_factory=lambda _: model)
    assert run_row(database, reader.id).status == 'completed'
    assert 'ORIGINAL SHARED ANSWER' in str(model.requests[-1].messages)
    with database() as db:
        manifest = db.get(RunRecord, reader.id).context_manifest
        assert any(d['kind'] == 'history' and d['resource_id'] == str(source_run.id) for d in manifest['dependencies'])
    with database() as db:
        revoke_resource_grant(db, principal, grants[0].id)
    with database() as db:
        next_run, _ = create_run(db, principal, tenant.id, session.id, message='next', idempotency_key='next')
    safe = FakeModel([[ModelChunk('text', text='safe')]])
    run_once(database, 'w', model_factory=lambda _: safe)
    assert run_row(database, next_run.id).status == 'completed'
    assert 'DERIVED ANSWER' not in str(safe.requests[0].messages)


def test_history_sources_obey_the_current_agents_memory_policy(database):
    from nexus_platform.runs.messages import histories_allowed
    _, _, session, run, _ = stack(database)
    _publish(database, run, 'private fact', 'secret')
    run_once(database, 'w', model_factory=lambda _: FakeModel([[ModelChunk('text', text='answer')]]))
    with database() as db:
        source = db.get(RunRecord, run.id)
        assert histories_allowed(db, [source])[source.id]
        viewer = SimpleNamespace(tenant_id=source.tenant_id, principal_id=source.principal_id,
                                 config_snapshot={'budgets': {'memory': {'enabled': False}}})
        assert not histories_allowed(db, [source], viewer=viewer)[source.id]
