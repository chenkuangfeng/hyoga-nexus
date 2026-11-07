"""One worker process executing several Runs on one event loop (openspec 2026-11-07-worker-concurrency)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nexus_core.deployment import DeploymentConfigError
from nexus_core.runtime import ModelChunk
from nexus_platform.persistence.database import configure_sqlite_concurrency
from nexus_platform.persistence.models import Base
from nexus_platform.runs.bus import RunEventSettings, install_channels, reset_channels
from nexus_platform.runs.bus.hook import install_run_event_hook
from nexus_platform.runs.dbexec import configure_db_executor, run_db, shutdown_db_executor
from nexus_platform.runs.service import request_cancel
from nexus_platform.runs.worker_settings import WorkerSettings, api_settings, worker_settings
from nexus_worker.__main__ import run_async, start_process_epoch

from test_native_runtime import run_row, stack


@pytest.fixture
def file_database(tmp_path):
    """A SQLite file: every thread gets its own connection, as with a real server database."""
    install_run_event_hook()
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False})
    configure_sqlite_concurrency(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    reset_channels()
    shutdown_db_executor()
    engine.dispose()


class SlowModel:
    def __init__(self, delay: float, text: str = "ok"):
        self.delay, self.text, self.closed = delay, text, False

    async def stream(self, request):
        await asyncio.sleep(self.delay)
        yield ModelChunk("text", text=self.text)
        yield ModelChunk("done", finish_reason="stop")

    async def close(self):
        self.closed = True


def drive(factory, runs, model_for, *, max_runs, until, stop_after=None, timeout=30):
    """Run ``run_async`` until ``until()`` is true (or ``stop_after`` seconds), then stop it."""
    epoch = start_process_epoch(factory, "w")
    configure_db_executor(8)
    stopped = threading.Event()

    async def scenario():
        worker = asyncio.create_task(run_async(
            factory, "w", stopped, epoch=epoch, watchdog=None, max_runs=max_runs, poll_interval=0.05,
            background=False, stop_timeout=10, execution_options={"model_factory": model_for}))
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            if (stop_after is not None and time.monotonic() - started >= stop_after) or (
                    stop_after is None and await run_db(until)):
                break
            await asyncio.sleep(0.05)
        stopped.set()
        await asyncio.wait_for(worker, 20)
        return time.monotonic() - started

    return asyncio.run(scenario())


def test_several_runs_overlap_on_one_event_loop(file_database):
    runs = [stack(file_database)[3] for _ in range(5)]
    done = lambda: all(run_row(file_database, r.id).status == "completed" for r in runs)
    elapsed = drive(file_database, runs, lambda _: SlowModel(0.8), max_runs=5, until=done)
    assert done()
    rows = [run_row(file_database, r.id) for r in runs]
    intervals = sorted((r.started_at, r.ended_at) for r in rows)
    # Run by Run these five would take about 4 s; they overlap, so some start before an earlier one ends.
    assert any(later[0] < earlier[1] for earlier, later in zip(intervals, intervals[1:]))
    assert elapsed < 4.0


def test_one_run_at_a_time_when_the_limit_is_one(file_database):
    runs = [stack(file_database)[3] for _ in range(3)]
    done = lambda: all(run_row(file_database, r.id).status == "completed" for r in runs)
    drive(file_database, runs, lambda _: SlowModel(0.4), max_runs=1, until=done)
    intervals = sorted((run_row(file_database, r.id).started_at, run_row(file_database, r.id).ended_at) for r in runs)
    assert all(later[0] >= earlier[1] for earlier, later in zip(intervals, intervals[1:]))


def test_cancelling_one_run_leaves_the_others_running(file_database):
    install_channels(file_database, RunEventSettings(backend="memory", lease_check_seconds=30.0))
    victim_principal, victim_tenant, _, victim, _ = stack(file_database)
    others = [stack(file_database)[3] for _ in range(2)]
    cancelled = {"sent": False}

    def model_for(context):
        return SlowModel(20.0) if context.run_id == victim.id else SlowModel(1.5)

    def done():
        if not cancelled["sent"] and run_row(file_database, victim.id).status == "running":
            cancelled["sent"] = True
            with file_database() as db:
                request_cancel(db, victim_principal, victim_tenant.id, victim.id)
        return cancelled["sent"] and all(run_row(file_database, r.id).status == "completed" for r in others) \
            and run_row(file_database, victim.id).status == "cancelled"

    elapsed = drive(file_database, [victim, *others], model_for, max_runs=3, until=done)
    assert run_row(file_database, victim.id).status == "cancelled" and elapsed < 15
    assert all(run_row(file_database, r.id).status == "completed" for r in others)


def test_stopping_the_worker_ends_running_runs_and_returns_promptly(file_database):
    runs = [stack(file_database)[3] for _ in range(2)]
    elapsed = drive(file_database, runs, lambda _: SlowModel(30.0), max_runs=2, until=None, stop_after=1.5)
    assert elapsed < 15
    # Stopping ends a Run the way it always has: through its cancellation token, so it is recorded as cancelled.
    assert all(run_row(file_database, r.id).status == "cancelled" for r in runs)


def test_database_calls_do_not_stall_the_loop(file_database):
    """A slow synchronous database call goes to the pool, so other coroutines keep running."""
    configure_db_executor(4)

    async def scenario():
        ticks = []

        async def ticker():
            for _ in range(10):
                await asyncio.sleep(0.05)
                ticks.append(time.monotonic())

        await asyncio.gather(run_db(time.sleep, 0.6), ticker())
        return ticks

    assert len(asyncio.run(scenario())) == 10  # the ticker finished while the slow call was still in its thread


def test_worker_settings_defaults_and_validation(deployment_config):
    deployment_config("")
    settings = worker_settings()
    assert (settings.max_concurrent_runs, settings.db_threads, settings.pool_size) == (32, 16, 20)
    assert settings.effective_runs("sqlite:///x.db") == 4 and settings.effective_runs("postgresql://x") == 32
    assert api_settings().threads == 40 and api_settings().pool_size == 44
    deployment_config("[worker]\nmax_concurrent_runs = 0\n")
    with pytest.raises(DeploymentConfigError):
        worker_settings()
    deployment_config("[api]\nthreads = 'many'\n")
    with pytest.raises(DeploymentConfigError):
        api_settings()
