"""Text delta batching (P6) and grouped Run writes (P7).

Batching changes only event granularity: the concatenated text and the persisted assistant
message are identical to the unbatched behavior.
"""
import asyncio
import time

from sqlalchemy import select

from nexus_core.runtime import ModelChunk, ModelRequest, RuntimeFault
from nexus_platform.persistence.models import MessageRecord, RunEventRecord
from nexus_worker.__main__ import run_once
from nexus_runtimes.native.engine.cancellation import CancellationToken
from nexus_runtimes.native.engine.turn import collect_response

from test_platform import database  # noqa: F401 (pytest fixture)
from test_native_runtime import FakeModel, stack


class RecordingStore:
    def __init__(self):
        self.events = []  # (monotonic time, kind, payload)

    async def emit(self, kind, payload):
        self.events.append((time.monotonic(), kind, payload))

    def deltas(self):
        return [payload['text'] for _, kind, payload in self.events if kind == 'message.delta']


class ScriptedModel:
    """Yields (delay_before_chunk_seconds, chunk) pairs."""
    def __init__(self, script):
        self.script = script

    async def stream(self, request):
        for delay, chunk in self.script:
            if delay:
                await asyncio.sleep(delay)
            yield chunk


REQUEST = ModelRequest((), (), 1000)
DONE = ModelChunk('done', finish_reason='stop')


async def _batched_deltas_concatenate_to_the_same_text():
    chunks = [ModelChunk('text', text=f'w{i} ') for i in range(40)]
    script = [(0, c) for c in chunks] + [(0, DONE)]
    expected = ''.join(c.text for c in chunks)

    unbatched = RecordingStore()
    result = await collect_response(ScriptedModel(script), REQUEST, CancellationToken(), unbatched, 1, 5, flush_ms=0)
    assert result.text == expected
    assert ''.join(unbatched.deltas()) == expected
    assert len(unbatched.deltas()) == 40

    batched = RecordingStore()
    result = await collect_response(ScriptedModel(script), REQUEST, CancellationToken(), batched, 1, 5,
                                    flush_ms=10_000, flush_chars=10_000)
    assert result.text == expected
    assert ''.join(batched.deltas()) == expected
    assert len(batched.deltas()) == 1  # nothing forces an earlier flush; the batch flushes at stream end


async def _character_threshold_flushes_early():
    script = [(0, ModelChunk('text', text='x' * 30)) for _ in range(5)] + [(0, DONE)]
    store = RecordingStore()
    await collect_response(ScriptedModel(script), REQUEST, CancellationToken(), store, 1, 5,
                           flush_ms=10_000, flush_chars=60)
    assert [len(d) for d in store.deltas()] == [60, 60, 30]


async def _window_flushes_while_the_model_is_silent():
    # The first text must reach the store while the model is still silent before the second chunk.
    script = [(0, ModelChunk('text', text='first')), (0.4, ModelChunk('text', text='second')), (0, DONE)]
    store = RecordingStore()
    started = time.monotonic()
    await collect_response(ScriptedModel(script), REQUEST, CancellationToken(), store, 1, 5,
                           flush_ms=100, flush_chars=10_000)
    first_flush = next(t for t, kind, _ in store.events if kind == 'message.delta')
    assert first_flush - started < 0.3
    assert ''.join(store.deltas()) == 'firstsecond'


async def _cancellation_is_observed_while_a_batch_is_open():
    script = [(0, ModelChunk('text', text='partial')), (5, DONE)]
    token = CancellationToken()
    asyncio.get_running_loop().call_later(0.2, token.cancel)
    try:
        await collect_response(ScriptedModel(script), REQUEST, token, RecordingStore(), 1, 10, flush_ms=100)
    except RuntimeFault as exc:
        assert exc.code == 'cancelled'
    else:
        raise AssertionError('cancellation was not observed')


def test_batched_deltas_concatenate_to_the_same_text():
    asyncio.run(_batched_deltas_concatenate_to_the_same_text())


def test_character_threshold_flushes_early():
    asyncio.run(_character_threshold_flushes_early())


def test_window_flushes_while_the_model_is_silent():
    asyncio.run(_window_flushes_while_the_model_is_silent())


def test_cancellation_is_observed_while_a_batch_is_open():
    asyncio.run(_cancellation_is_observed_while_a_batch_is_open())


def test_worker_run_persists_one_assistant_message_and_grouped_completion(database):
    principal, tenant, session, run, _ = stack(database)
    chunks = [ModelChunk('text', text=part) for part in ['Hello', ', ', 'world', '!']]
    model = FakeModel([chunks])  # FakeModel appends the terminal done item itself
    run_once(database, 'worker', model_factory=lambda _: model)
    with database() as db:
        assistant = db.scalars(select(MessageRecord).where(MessageRecord.session_id == session.id,
                                                           MessageRecord.role == 'assistant')).all()
        assert [m.content for m in assistant] == ['Hello, world!']
        events = [e.event_type for e in db.scalars(select(RunEventRecord).where(RunEventRecord.run_id == run.id)
                                                    .order_by(RunEventRecord.sequence))]
    deltas = [e for e in events if e == 'message.delta']
    assert 1 <= len(deltas) <= 4  # batched by the default window; never more than one per chunk
    assert events.index('model.completed') < events.index('turn.completed')
