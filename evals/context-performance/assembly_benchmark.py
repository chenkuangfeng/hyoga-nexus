"""Measure context preparation and structural scaling against a selected source tree.

Usage: .venv/bin/python evals/context-performance/assembly_benchmark.py --root /path/to/tree --json /tmp/result.json
The same installed dependencies serve both trees; PYTHONPATH points at that tree's Python source.
Only scripted models are used. Results are platform measurements, not answer-quality/provider-cache claims.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import threading
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--json', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    paths = [*root.glob('packages/*/src'), *root.glob('apps/*/src'), root / 'evals/context-performance']
    sys.path[:0] = [str(path) for path in paths]
    import harness
    from cases import CASES
    from sqlalchemy import event, insert
    from sqlalchemy.engine import Engine
    from sqlalchemy.pool import Pool
    from nexus_runtimes.native.context.assembler import ContextAssembler
    from nexus_platform.runs import preparation
    from nexus_platform.persistence.models import MessageRecord
    from nexus_platform.runs.service import create_run
    from nexus_core.platform import utc_now
    from nexus_core.runtime import ToolDefinition
    from nexus_tools.gateway import AuthorizedToolGateway
    from nexus_tools.registry import ToolRegistry, RegisteredTool

    samples, view_samples, prefix_digests = [], [], set()
    local = threading.local()
    original_view = ContextAssembler.view
    def measured_view(self, history, *a, **kw):
        started = time.perf_counter()
        result = original_view(self, history, *a, **kw)
        view_samples.append((time.perf_counter() - started) * 1000)
        tools = kw.get('definitions') or ()
        tool_text = json.dumps([{'name': d.name, 'description': d.description, 'parameters': d.parameters}
                                for d in tools], sort_keys=True, ensure_ascii=False)
        prefix = (history[0].content if history else '') + tool_text
        prefix_digests.add(hashlib.sha256(prefix.encode()).hexdigest())
        return result
    ContextAssembler.view = measured_view
    def checkout(connection, record, proxy):
        if getattr(local, 'active', False):
            local.checkout_at = time.perf_counter()
    def checkin(connection, record):
        if getattr(local, 'active', False) and local.checkout_at is not None:
            local.connection_ms += (time.perf_counter() - local.checkout_at) * 1000
            local.checkout_at = None
    event.listen(Pool, 'checkout', checkout)
    event.listen(Pool, 'checkin', checkin)
    original = preparation.ExecutionPreparer.prepare

    def count(*_):
        if getattr(local, 'active', False): local.sql += 1
    event.listen(Engine, 'before_cursor_execute', count)

    def measured(self, *a, **kw):
        # Database fixtures allocate many objects before preparation. Collect outside the timed
        # region, then suspend cyclic GC in both source trees so a fixture's deferred collection
        # cannot masquerade as assembly latency. Production end-to-end timings remain separate.
        gc.collect()
        was_enabled = gc.isenabled()
        gc.disable()
        local.active, local.sql, local.connection_ms, local.checkout_at = True, 0, 0.0, None
        started = time.perf_counter()
        try:
            return original(self, *a, **kw)
        finally:
            samples.append({'ms': (time.perf_counter() - started) * 1000, 'sql': local.sql, 'connection_ms': local.connection_ms})
            local.active = False
            if was_enabled:
                gc.enable()
    preparation.ExecutionPreparer.prepare = measured
    # Warm imports, schema mappings and the worker event loop before measurement.
    harness.run_case(CASES[0]); harness.run_case(CASES[0])
    samples.clear(); view_samples.clear(); prefix_digests.clear()
    results = harness.run_all()
    preparation.ExecutionPreparer.prepare = original
    event.remove(Engine, 'before_cursor_execute', count)
    event.remove(Pool, 'checkout', checkout)
    event.remove(Pool, 'checkin', checkin)
    ContextAssembler.view = original_view

    catalog = []
    for size in (100, 1000):
        registry = ToolRegistry()
        for i in range(size):
            registry.register(RegisteredTool(ToolDefinition(f'tool_{i}', 'description', {'type': 'object'}), lambda *_: None))
        class Access:
            def __init__(self): self.scalar, self.bulk = 0, 0
            async def authorize(self, *_): self.scalar += 1; return 'binding'
            async def authorize_many(self, requested): self.bulk += 1; return set(requested)
        access = Access()
        gateway = AuthorizedToolGateway(registry, access, {d.name: d.version for d in registry.definitions()},
            run_id='benchmark', session_id='benchmark', tenant_id='benchmark')
        started = time.perf_counter()
        definitions = asyncio.run(gateway.definitions())
        catalog.append({'tools': size, 'offered': len(definitions), 'scalar_dispatches': access.scalar,
                        'bulk_dispatches': access.bulk, 'ms': (time.perf_counter() - started) * 1000})

    engine, factory, _ = harness.new_database()
    principal, tenant_id, session_id = harness.open_session(factory, CASES[0], {})
    with factory() as db:
        run, _ = create_run(db, principal, tenant_id, session_id, message='task', idempotency_key='scale')
    with factory() as db, db.begin():
        for start in range(0, 10000, 200):
            db.execute(insert(MessageRecord), [dict(id=uuid4(), session_id=session_id, run_id=run.id,
                sequence=i + 2, role='user' if i % 10 == 0 else 'tool', content='payload' * 20,
                runtime_metadata={'tool_calls': [], 'origin': 'runtime'}, created_at=utc_now())
                for i in range(start, start + 200)])
    timings = []
    for _ in range(5):
        with factory() as db:
            started = time.perf_counter()
            fn = preparation._message_rows
            rows = fn(db, session_id, uuid4()) if 'current_run_id' in inspect.signature(fn).parameters else fn(db, session_id)
            timings.append((time.perf_counter() - started) * 1000)
    retained_users = sum(r['role'] == 'user' for r in rows)
    assert retained_users == 1001
    engine.dispose()
    elapsed = sorted(s['ms'] for s in samples)
    output = {'source_root': str(root), 'scripted_only': True, 'gc_controlled_prepare': True, 'cases': len(results),
        'completed': sum(r['completed'] for r in results), 'preparations': len(samples),
        'prepare_p50_ms': statistics.median(elapsed), 'prepare_p95_ms': elapsed[max(0, (len(elapsed) * 95 + 99) // 100 - 1)],
        'connection_hold_p50_ms': statistics.median(s['connection_ms'] for s in samples),
        'request_view_p50_ms': statistics.median(view_samples),
        'request_prefix_digests': sorted(prefix_digests),
        'prepare_sql_total': sum(s['sql'] for s in samples), 'prepare_sql_p50': statistics.median(s['sql'] for s in samples),
        'input_chars': sum(r['totals']['input_chars'] for r in results), 'catalog': catalog,
        'history_10k': {'rows_materialized': len(rows), 'user_rows_retained': retained_users,
                        'p50_ms': statistics.median(timings)}, 'samples': samples}
    args.json.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in output.items() if k != 'samples'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
