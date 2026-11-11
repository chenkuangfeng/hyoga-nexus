"""Benchmark of the Run event bus backends (openspec 2026-11-07-run-event-streaming 8.1).

Measures what a viewer feels, not what the bus does internally:

* ``publish``  - cost of one ``publish`` call from the producer side (memory, redis; the database backend publishes
  nothing, the Run's own commit is the publication).
* ``fanout``   - delivery latency (producer stamp -> subscriber receipt, one process, so one clock) and lost events
  with 1, 10 and 100 subscribers on one Run.
* ``runs``     - the same with many Runs at once, one subscriber each.

The database backend is driven by committing ``run_events`` rows (SQLite file, no foreign keys), because that is
what feeds its poller. Redis needs a server: start one and pass ``--redis-url``.

    uv run python evals/run-events/bench.py --backends memory,database,redis --redis-url redis://127.0.0.1:6391/0
"""
from __future__ import annotations

import argparse
import asyncio
import json
import resource
import statistics
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nexus_core.run_events import BusEvent, End
from nexus_platform.persistence.models import Base, RunEventRecord
from nexus_platform.runs.bus.database import DatabaseBus
from nexus_platform.runs.bus.memory import MemoryBus


def percentiles(values_ms: list[float]) -> dict:
    if not values_ms:
        return {"p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values_ms)

    def at(q: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2)
    return {"p50": at(0.50), "p95": at(0.95), "p99": at(0.99), "max": round(ordered[-1], 2)}


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


class Harness:
    """One backend plus the way to produce a durable event on it."""

    def __init__(self, name: str, redis_url: str):
        self.name = name
        self._tmp = None
        if name == "memory":
            self.bus = MemoryBus(maxlen=100_000)
        elif name == "redis":
            from nexus_platform.runs.bus.redis_backend import RedisBus
            self.bus = RedisBus(redis_url, prefix=f"bench{uuid4().hex[:6]}", maxlen=100_000, retention_seconds=30)
            if not self.bus.ping():
                raise SystemExit(f"redis is not reachable at {redis_url}")
        elif name == "database":
            self._tmp = tempfile.TemporaryDirectory()
            self.engine = create_engine(f"sqlite:///{self._tmp.name}/bench.db", connect_args={"timeout": 30})
            Base.metadata.create_all(self.engine)
            self.factory = sessionmaker(self.engine)
            self.bus = DatabaseBus(self.factory, poll_min_ms=250, poll_max_ms=1000)
        else:
            raise SystemExit(f"unknown backend {name}")

    def produce(self, run_id, sequence: int) -> None:
        stamp = time.monotonic_ns()
        if self.name == "database":
            with self.factory() as db:
                db.add(RunEventRecord(id=uuid4(), run_id=run_id, sequence=sequence, event_type="tool.started",
                                      payload={"t": stamp}, occurred_at=datetime.now(timezone.utc)))
                db.commit()
        else:
            self.bus.publish(BusEvent(str(run_id), "tool.started", {"t": stamp}, sequence))

    def finish(self, run_id) -> None:
        if self.name != "database":
            self.bus.publish_end(run_id)

    def close(self) -> None:
        self.bus.close()
        if self._tmp is not None:
            self.engine.dispose()
            self._tmp.cleanup()


def bench_publish(h: Harness, count: int) -> dict | None:
    if h.name == "database":
        return None
    run_id, costs = uuid4(), []
    started = time.perf_counter()
    for sequence in range(1, count + 1):
        t0 = time.perf_counter_ns()
        h.bus.publish(BusEvent(str(run_id), "message.delta", {"text": "x" * 40}, None))
        costs.append((time.perf_counter_ns() - t0) / 1e6)
    elapsed = time.perf_counter() - started
    return {"events": count, "per_second": round(count / elapsed), "latency_ms": percentiles(costs)}


async def _consume(h: Harness, run_id, expected: int, latencies: list[float], deadline: float) -> int:
    received = 0
    async for item in h.bus.subscribe(run_id, after="0" if h.name == "database" else None, heartbeat=1.0):
        if isinstance(item, BusEvent) and item.sequence is not None:
            latencies.append((time.monotonic_ns() - item.payload["t"]) / 1e6)
            received += 1
            if received >= expected:
                break
        elif isinstance(item, End) or time.monotonic() > deadline:
            break
        if time.monotonic() > deadline:
            break
    return received


def _producer(h: Harness, run_ids: list, events: int, rate: int, started: threading.Event) -> threading.Thread:
    def run() -> None:
        started.wait()
        interval = 1.0 / rate
        next_at = time.monotonic()
        for sequence in range(1, events + 1):
            for run_id in run_ids:
                h.produce(run_id, sequence)
            next_at += interval
            time.sleep(max(0.0, next_at - time.monotonic()))
        for run_id in run_ids:
            h.finish(run_id)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


async def _scenario(h: Harness, run_ids: list, subscribers_per_run: int, events: int, rate: int) -> dict:
    latencies: list[float] = []
    started = threading.Event()
    deadline = time.monotonic() + events / rate + 15
    tasks = [asyncio.create_task(_consume(h, run_id, events, latencies, deadline))
             for run_id in run_ids for _ in range(subscribers_per_run)]
    await asyncio.sleep(0.5)  # subscribers are attached before the first event
    before = rss_mb()
    producer = _producer(h, run_ids, events, rate, started)
    started.set()
    received = await asyncio.gather(*tasks)
    producer.join(timeout=5)
    expected = events * len(tasks)
    return {"subscribers": len(tasks), "runs": len(run_ids), "events_each": events, "rate_per_second": rate,
            "delivered": sum(received), "expected": expected, "lost": expected - sum(received),
            "latency_ms": percentiles(latencies), "rss_mb_growth": round(rss_mb() - before, 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backends", default="memory,database,redis")
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6391/0")
    parser.add_argument("--publish-events", type=int, default=20000)
    parser.add_argument("--events", type=int, default=200)
    parser.add_argument("--rate", type=int, default=100, help="events per second per Run")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    report: dict = {"python": sys.version.split()[0], "results": {}}
    for name in args.backends.split(","):
        h = Harness(name, args.redis_url)
        try:
            result = {"publish": bench_publish(h, args.publish_events)}
            for count in (1, 10, 100):
                result[f"fanout_{count}"] = asyncio.run(_scenario(h, [uuid4()], count, args.events, args.rate))
            # Fifty Runs at once. The database backend is fed by committed rows, and a SQLite file takes only so many
            # commits per second, so it gets a tenth of the rate: otherwise the producer, not the bus, is measured.
            divisor = 10 if name == "database" else 2
            result["runs_50"] = asyncio.run(_scenario(h, [uuid4() for _ in range(50)], 1, max(20, args.events // divisor),
                                                      max(5, args.rate // divisor)))
        finally:
            h.close()
        report["results"][name] = result
        print(f"== {name}")
        print(json.dumps(result, indent=1))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
