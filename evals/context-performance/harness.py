"""Baseline harness for the context-performance change (openspec 2026-11-01-context-token-performance, section 一).

Each case runs in its own in-memory database through the real worker path (`run_once`), so the
numbers include authorization, preparation, the engine, tool gateway and persistence. Recorded per
turn: database transactions, run events, model requests, characters sent to the model, and
wall-clock time. Cached-token counts and model latency come from a real provider only and are not
produced by the scripted model used here.

The default model is scripted, so these numbers measure platform work and input size, not answer
quality. Pass a `model_factory` to `run_case` to measure a real provider once one is configured.

Usage (from the repository root):
    uv run python evals/context-performance/harness.py
    uv run python evals/context-performance/harness.py --case followup-9000 --json out.json
    uv run python evals/context-performance/harness.py --behavior '{"tool_output_inline_limit": 4000}'
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_core.platform import Principal
from nexus_core.runtime import ModelChunk, ToolCall, ToolDefinition, ToolResult
from nexus_platform.agents.service import create_agent, publish_agent
from nexus_platform.authz.resources import register_resource
from nexus_platform.models.service import create_model_profile
from nexus_platform.persistence.models import Base, RunEventRecord, RunRecord
from nexus_platform.runs.service import create_run
from nexus_platform.sessions.service import create_session
from nexus_platform.tenants.service import create_tenant
from nexus_tools.builtins.tool_output import tool_output_tools
from nexus_tools.registry import RegisteredTool, ToolRegistry
from nexus_worker.__main__ import run_once

from cases import CASES, Case, Turn

MARKER = 'END size={size}'


def fetch_body(size: int) -> str:
    """Deterministic document of `size` characters that ends in a marker naming the size."""
    filler = 'record data row '
    return (filler * (size // len(filler) + 1))[:max(0, size - len(MARKER))] + MARKER.format(size=size)


class ScriptedModel:
    """Plays one scripted turn: tool-call rounds first, then the final answer. Records every request."""

    def __init__(self, turn: Turn, meter: list[int]):
        self.turn, self.meter, self.step, self.requests = turn, meter, 0, []

    async def stream(self, request):
        self.requests.append(request)
        self.meter.append(sum(len(m.content) + sum(len(c.arguments) for c in m.tool_calls) for m in request.messages))
        if self.step < len(self.turn.rounds):
            calls = self.turn.rounds[self.step]
            self.step += 1
            for name, arguments in calls:
                yield ModelChunk('tool_call', tool_call=ToolCall(str(uuid4()), name, json.dumps(arguments)))
            yield ModelChunk('done', finish_reason='tool_calls')
        else:
            yield ModelChunk('text', text=self.turn.answer)
            yield ModelChunk('done', finish_reason='stop')

    async def close(self):
        pass


def build_registry(reader: bool) -> ToolRegistry:
    tools = ToolRegistry()

    async def fetch(arguments, context):
        return ToolResult(fetch_body(arguments['size']))

    schema = {'type': 'object', 'properties': {'size': {'type': 'integer', 'minimum': 0, 'maximum': 100000}},
              'required': ['size'], 'additionalProperties': False}
    tools.register(RegisteredTool(ToolDefinition('fetch', 'Fetch a document of a given size.', schema),
                                  fetch, lambda result: result.data))
    if reader:
        for tool in tool_output_tools():
            tools.register(tool)
    return tools


def new_database():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    with engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    transactions = [0]

    @event.listens_for(engine, 'begin')
    def count_transaction(connection):
        transactions[0] += 1

    return engine, sessionmaker(bind=engine, expire_on_commit=False, autoflush=False), transactions


def open_session(factory, case: Case, behavior: dict):
    """Create tenant, agent with the case's bindings, and a session. Mirrors the test fixtures."""
    principal = Principal('eval-owner', 'eval')
    names = ['fetch'] + (['read_tool_output'] if case.reader else [])
    with factory() as db:
        tenant = create_tenant(db, principal, 'Eval')
        with db.begin():
            for name in names:
                register_resource(db, tenant_id=tenant.id, kind='tool', resource_id=name, version_id='v1')
        _, model = create_model_profile(db, principal, tenant.id, name='model', provider='test', model_name='fake', options={})
        agent = create_agent(db, principal, tenant.id, name='Eval', description='', runtime_type='native',
            instructions='Answer using the tools when needed.', model_profile_version_id=model.id,
            budgets={'max_tokens': 1000000, 'behavior': behavior},
            bindings=[{'kind': 'tool', 'resource_id': name, 'resource_version_id': 'v1',
                       'source_tenant_id': str(tenant.id), 'config': {}} for name in names])
        version = publish_agent(db, principal, tenant.id, agent.id)
        session = create_session(db, principal, tenant.id, agent_version_id=version.id)
        return principal, tenant.id, session.id


def run_case(case: Case, behavior: dict | None = None, model_factory=None) -> dict:
    """Run every turn of one case and return its measurements. `model_factory(turn, meter)` may replace the script."""
    behavior = behavior or {}
    engine, factory, transactions = new_database()
    try:
        principal, tenant_id, session_id = open_session(factory, case, behavior)
        registry = build_registry(case.reader)
        turns = []
        for index, turn in enumerate(case.turns):
            with factory() as db:
                run, _ = create_run(db, principal, tenant_id, session_id, message=f'{case.name} question {index}',
                                    idempotency_key=f'{case.name}-{index}')
                run_id = run.id
            meter: list[int] = []
            model = model_factory(turn, meter) if model_factory else ScriptedModel(turn, meter)
            tx_before, started = transactions[0], time.perf_counter()
            run_once(factory, 'eval', model_factory=lambda _: model, registry_factory=lambda _: registry)
            elapsed_ms = (time.perf_counter() - started) * 1000
            with factory() as db:
                events = db.scalar(select(func.count()).select_from(RunEventRecord).where(RunEventRecord.run_id == run_id))
                status = db.scalar(select(RunRecord.status).where(RunRecord.id == run_id))
            turns.append({'turn': index, 'status': status, 'requests': len(meter), 'input_chars': sum(meter),
                          'transactions': transactions[0] - tx_before, 'events': events, 'wall_ms': round(elapsed_ms, 2)})
        return {'case': case.name, 'reader': case.reader, 'turns': turns,
                'totals': {key: sum(turn[key] for turn in turns) for key in ('requests', 'input_chars', 'transactions', 'events', 'wall_ms')},
                'completed': all(turn['status'] == 'completed' for turn in turns)}
    finally:
        engine.dispose()


def run_all(cases=CASES, behavior: dict | None = None, model_factory=None) -> list[dict]:
    return [run_case(case, behavior, model_factory) for case in cases]


def render(results: list[dict]) -> str:
    header = f"{'case':<26}{'turns':>6}{'reqs':>6}{'input_chars':>13}{'tx':>6}{'events':>8}{'wall_ms':>10}  status"
    lines = [header, '-' * len(header)]
    for result in results:
        totals = result['totals']
        lines.append(f"{result['case']:<26}{len(result['turns']):>6}{totals['requests']:>6}{totals['input_chars']:>13}"
                     f"{totals['transactions']:>6}{totals['events']:>8}{totals['wall_ms']:>10.1f}  "
                     f"{'completed' if result['completed'] else 'NOT COMPLETED'}")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--case', action='append', help='run only the named case (repeatable)')
    parser.add_argument('--behavior', default='{}', help='JSON object merged into the Native behavior settings')
    parser.add_argument('--json', type=Path, help='write full per-turn measurements to this file')
    args = parser.parse_args(argv)
    cases = [case for case in CASES if not args.case or case.name in args.case]
    results = run_all(cases, json.loads(args.behavior))
    print(render(results))
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result['completed'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
