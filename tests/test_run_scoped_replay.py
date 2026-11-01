"""Run-scoped replay (P10): earlier Runs contribute their answers, not their tool exchanges."""
from nexus_core.runtime import ModelChunk, ToolResult
from nexus_platform.runs.service import create_run
from nexus_worker.__main__ import run_once

from test_platform import database  # noqa: F401 (pytest fixture)
from test_native_runtime import FakeModel, call, registry, stack


def test_tool_output_stays_whole_within_its_run_and_is_not_replayed_later(database):
    principal, tenant, session, run, _ = stack(database, ['echo'])

    async def echo(args, context):
        return ToolResult('secret-tool-output')

    first = FakeModel([[call('echo', '{"text":"go"}')], [ModelChunk('text', text='done-A')]])
    run_once(database, 'worker', model_factory=lambda _: first, registry_factory=lambda _: registry(echo))
    # Within the Run that made the call, the model saw the full result on its next request.
    assert any(m.content == 'secret-tool-output' for m in first.requests[1].messages)

    with database() as db:
        create_run(db, principal, tenant.id, session.id, message='Follow-up', idempotency_key='follow-up')
    later = FakeModel([[ModelChunk('text', text='ok')]])
    run_once(database, 'worker', model_factory=lambda _: later)
    messages = later.requests[0].messages
    contents = [m.content for m in messages]
    assert 'done-A' in contents  # the earlier final answer is kept
    assert 'secret-tool-output' not in contents  # the earlier tool result is not replayed
    assert not any(m.role == 'tool' for m in messages)
    assert not any(m.tool_calls for m in messages)  # neither is the earlier call envelope
