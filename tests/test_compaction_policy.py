"""Context compaction thresholds, summary bounds, and the configured compaction model (P3)."""
import asyncio

from nexus_core.runtime import ModelChunk, ModelMessage, RuntimeProgress
from nexus_core.runtime.budgets import ExecutionBudget
from nexus_runtimes.native.context.compaction import compact, compact_within

from test_native_runtime import FakeModel, stack
from test_platform import database  # noqa: F401 (pytest fixture)
from nexus_worker.__main__ import run_once


class Store:
    def __init__(self):
        self.events, self.summaries = [], []

    async def emit(self, kind, payload):
        self.events.append((kind, payload))

    async def save_progress(self, progress):
        pass

    async def save_summary(self, summary, source_id):
        self.summaries.append((summary, source_id))


class Summarizer:
    def __init__(self, text):
        self.text, self.calls, self.closed = text, 0, False

    async def stream(self, request):
        self.calls += 1
        yield ModelChunk('text', text=self.text)

    async def close(self):
        self.closed = True


def _history(old, answer):
    return [ModelMessage('system', 'S'), ModelMessage('user', 'o' * old, source_id='m1'),
            ModelMessage('assistant', answer, source_id='m2'), ModelMessage('user', 'now' * 30, source_id='m3')]


def _run(messages, limit, *, model=None, store=None, summary_max=8000, summarizer_factory=None, high=None, low=None):
    store = store or Store()
    budget = ExecutionBudget(max_tokens=100000, model_timeout_seconds=30, max_output_tokens=2048)
    result = asyncio.run(compact(model or Summarizer("summary"), tuple(messages), limit, _Token(), budget, RuntimeProgress(), store,
                                 high=high, low=low, summary_max=summary_max, summarizer_factory=summarizer_factory))
    return result, store


class _Token:
    def check(self):
        pass

    async def wait(self):
        await asyncio.Event().wait()


def test_usage_between_low_and_high_does_not_compact():
    messages = _history(1000, 'a' * 600)  # size ~1700: above the low target, below the high threshold
    model = Summarizer('unused')
    (result, removed), store = _run(messages, 2000, model=model)
    assert tuple(result) == tuple(messages) and removed == 0
    assert model.calls == 0 and store.summaries == [] and store.events == []


def test_usage_above_high_is_summarized_under_the_low_target():
    messages = _history(1500, 'a' * 1500)
    (result, removed), store = _run(messages, 2000)
    assert removed == 2 and result[1].content.startswith('[Historical summary')
    assert store.summaries == [(result[1].content, 'm2')]  # cut point is the last older row


def test_summary_is_cut_to_the_configured_maximum_before_storage():
    messages = _history(15000, 'a' * 15000)
    (result, removed), store = _run(messages, 30000, model=Summarizer('y' * 5000), summary_max=300)
    assert removed == 2
    stored = store.summaries[0][0]
    assert stored.endswith('y' * 300) and 'y' * 301 not in stored


def test_summary_failure_degrades_to_excerpts_and_emits_the_reason():
    messages = _history(1500, 'a' * 1500)
    (result, removed), store = _run(messages, 2000, model=Summarizer(''))
    assert ('context.summary_degraded', {'reason': 'model_response_unusable'}) in store.events
    assert store.summaries == []  # nothing is persisted from a degraded attempt
    assert 'Earlier conversation excerpts' in result[1].content


def test_configured_compaction_model_is_used_and_released_instead_of_the_run_model():
    messages = _history(1500, 'a' * 1500)
    run_model, configured = Summarizer('wrong'), Summarizer('right')
    (result, removed), store = _run(messages, 2000, model=run_model, summarizer_factory=lambda: configured)
    assert configured.calls == 1 and run_model.calls == 0
    assert configured.closed and not run_model.closed  # the configured client is ours to close
    assert 'right' in result[1].content


def test_unavailable_compaction_model_degrades_without_failing():
    messages = _history(1500, 'a' * 1500)
    run_model = Summarizer('wrong')
    def unavailable():
        raise PermissionError('not authorized')
    (result, removed), store = _run(messages, 2000, model=run_model, summarizer_factory=unavailable)
    assert ('context.summary_degraded', {'reason': 'compaction_model_unavailable'}) in store.events
    assert run_model.calls == 0 and store.summaries == []
    assert removed >= 1


def test_deterministic_path_is_a_no_op_at_or_below_high_threshold():
    messages = _history(1000, 'a' * 600)
    assert compact_within(tuple(messages), high=2000, low=1200, limit=2000) == (tuple(messages), 0)


def test_run_uses_the_configured_compaction_model_end_to_end(database):
    behavior = {'summarize_context': True}
    principal, tenant, session, run, _ = stack(database, budgets={'max_tokens': 100000, 'max_context_chars': 2000,
                                                                  'behavior': behavior})
    first = FakeModel([[ModelChunk('text', text='A' * 2500)]])
    run_once(database, 'worker', model_factory=lambda _: first)
    from nexus_platform.runs.service import create_run
    with database() as db:
        create_run(db, principal, tenant.id, session.id, message='Second', idempotency_key='second')
    main, summarizer = FakeModel([[ModelChunk('text', text='ok')]]), FakeModel([[ModelChunk('text', text='short summary')]])
    run_once(database, 'worker', model_factory=lambda _: main, compaction_model_factory=lambda: summarizer)
    assert summarizer.requests and summarizer.closed
    assert not any('A' * 2500 in m.content for m in main.requests[0].messages)
    assert any('short summary' in m.content for m in main.requests[0].messages)
