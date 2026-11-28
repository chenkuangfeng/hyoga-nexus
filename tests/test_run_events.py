"""Run event channel: settings, backends, the commit hook, the subscription pipeline and embedded workers
(openspec 2026-11-07-run-event-streaming)."""
from __future__ import annotations

import asyncio
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.deployment import DeploymentConfigError
from nexus_core.run_events import END, HEARTBEAT, BusEvent, StreamGap
from nexus_core.runtime import ModelChunk
from nexus_platform.persistence.models import Base, RunEventRecord
from nexus_platform.runs.bus import (DeploymentSettings, RunEventSettings, build_channels, channels,
                                     deployment_settings, install_channels, reset_channels, run_event_settings)
from nexus_platform.runs.bus.hook import install_run_event_hook
from nexus_platform.runs.bus.memory import MemoryBus, MemoryControl, MemoryMarker
from nexus_platform.runs.bus.stream import StreamItem, stream_run_events
from nexus_platform.runs.service import request_cancel
from nexus_worker.__main__ import run_once

from test_native_runtime import FakeModel, run_row, stack
from test_platform import database  # noqa: F401 (pytest fixture)


@pytest.fixture(autouse=True)
def clean_channels():
    install_run_event_hook()
    reset_channels()
    yield
    reset_channels()


def event(run_id, kind, sequence=None, **payload):
    return BusEvent(str(run_id), kind, payload, sequence)


# -- settings -----------------------------------------------------------------------------------


def test_defaults_are_split_with_the_database_backend(deployment_config):
    deployment_config("")
    assert deployment_settings().mode == "split"
    settings = run_event_settings()
    assert settings.backend == "database" and settings.lease_check_seconds == 1.0


def test_embedded_mode_defaults_to_the_memory_bus_and_a_looser_database_check(deployment_config):
    deployment_config('[deployment]\nmode = "embedded"\n')
    assert run_event_settings().backend == "memory" and deployment_settings().embedded_workers == 4
    deployment_config('[deployment]\nmode = "embedded"\n[run_events]\nbackend = "redis"\n')
    assert run_event_settings().lease_check_seconds == 5.0


@pytest.mark.parametrize("text", [
    '[run_events]\nbackend = "memory"\n',                       # split mode cannot hand events between processes
    '[run_events]\nbackend = "kafka"\n',
    '[run_events]\nmaxlen = 3\n',
    '[run_events]\npoll_min_ms = 900\npoll_max_ms = 100\n',
    '[run_events]\nredis_url = "http://x"\n',
    '[deployment]\nmode = "both"\n',
    '[deployment]\nembedded_workers = 0\n',
])
def test_invalid_settings_stop_start_up(deployment_config, text):
    deployment_config(text)
    with pytest.raises(DeploymentConfigError):
        run_event_settings()


# -- memory bus ---------------------------------------------------------------------------------


async def collect(bus, run_id, after=None, limit=10, heartbeat=0.05):
    items = []
    async for item in bus.subscribe(run_id, after=after, heartbeat=heartbeat):
        items.append(item)
        if item is END or len(items) >= limit:
            break
    return items


def test_memory_bus_replays_in_order_then_ends():
    bus, run = MemoryBus(), uuid4()
    for index in range(3):
        bus.publish(event(run, "message.delta", text=str(index)))
    bus.publish_end(run)
    items = asyncio.run(collect(bus, run))
    assert [i.payload["text"] for i in items[:3]] == ["0", "1", "2"] and items[-1] is END
    after_two = asyncio.run(collect(bus, run, after=items[1].cursor))
    assert [i.payload["text"] for i in after_two[:-1]] == ["2"]


def test_memory_bus_reports_a_gap_when_the_cursor_was_trimmed():
    bus, run = MemoryBus(maxlen=3), uuid4()
    for index in range(8):
        bus.publish(event(run, "message.delta", text=str(index)))
    items = asyncio.run(collect(bus, run, after="2", limit=4))
    assert isinstance(items[0], StreamGap) and items[0].requested == "2"
    assert [i.payload["text"] for i in items[1:]] == ["5", "6", "7"]


def test_memory_bus_wakes_a_subscriber_from_another_thread_and_beats_when_idle():
    bus, run = MemoryBus(), uuid4()

    async def scenario():
        seen = []

        async def reader():
            async for item in bus.subscribe(run, after=None, heartbeat=0.05):
                seen.append(item)
                if isinstance(item, BusEvent):
                    return

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.2)
        threading.Thread(target=lambda: bus.publish(event(run, "message.delta", text="hi"))).start()
        await asyncio.wait_for(task, 2)
        return seen

    seen = asyncio.run(scenario())
    assert HEARTBEAT in seen and seen[-1].payload["text"] == "hi"


def test_memory_bus_wakes_a_subscriber_that_attached_before_the_first_event():
    """A viewer can connect before the Run publishes anything. It must be woken by the first event, not by the
    next heartbeat (15 s by default)."""
    bus, run = MemoryBus(), uuid4()

    async def scenario():
        async def reader():
            async for item in bus.subscribe(run, after=None, heartbeat=30.0):
                if isinstance(item, BusEvent):
                    return time.monotonic()

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.2)
        sent = time.monotonic()
        threading.Thread(target=lambda: bus.publish(event(run, "message.delta", text="first"))).start()
        return (await asyncio.wait_for(task, 3)) - sent

    assert asyncio.run(scenario()) < 1.0


def test_memory_bus_drops_the_empty_log_a_subscriber_created_for_a_run_that_never_published():
    bus, run = MemoryBus(retention_seconds=0.05), uuid4()

    async def scenario():
        gen = bus.subscribe(run, after=None, heartbeat=0.02)
        await gen.__anext__()            # a heartbeat: the subscriber is attached
        await gen.aclose()

    asyncio.run(scenario())
    time.sleep(0.1)
    bus.publish(event(uuid4(), "message.delta", text="other"))   # any publish purges
    assert str(run) not in bus._runs


def test_memory_producer_lease_and_control_and_marker():
    bus, run, session = MemoryBus(), uuid4(), uuid4()
    lease = bus.start_producer(run, "w")
    assert bus.producer_state(run) == "active" and bus.renew_producer(lease)
    bus.finish_producer(lease)
    assert bus.producer_state(run) == "untracked" and not bus.renew_producer(lease)
    control = MemoryControl()
    assert control.wait(run, 0.01) is False
    control.signal(run, "cancel")
    assert control.wait(run, 1) is True and control.wait(run, 0.01) is False
    marker = MemoryMarker()
    marker.claim(session, run, 60)
    assert marker.get(session) == str(run)
    marker.clear(session, uuid4())
    assert marker.get(session) == str(run)
    marker.clear(session, run)
    assert marker.get(session) is None


# -- subscription pipeline ----------------------------------------------------------------------


def make_page(stored):
    """A ``page`` over a mutable list of durable events plus a mutable status."""
    state = {"status": "running"}

    def page(after, size):
        return [e for e in stored if e.sequence > after][:size], state["status"]

    return page, state, (lambda: state["status"])


def drain(ch, run, after, page, status, publish):
    async def scenario():
        out = []
        task_publish = asyncio.get_running_loop().run_in_executor(None, publish)
        async for item in stream_run_events(ch, run, after, page, status):
            out.append(item)
        await task_publish
        return out

    return asyncio.run(asyncio.wait_for(scenario(), 10))


def test_pipeline_replays_dedupes_and_skips_text_of_completed_turns():
    ch, run = build_channels(lambda: None, RunEventSettings(backend="memory", heartbeat_seconds=1.0)), uuid4()
    stored = [event(run, "run.started", 1), event(run, "message.completed", 2, turn=0, text="old"),
              event(run, "turn.started", 3)]
    page, state, status = make_page(stored)

    def publish():
        time.sleep(0.1)
        ch.bus.publish(event(run, "message.delta", turn=0, text="old"))      # turn 0 is complete: dropped
        ch.bus.publish(event(run, "run.started", 1))                         # at or below the cursor: dropped
        ch.bus.publish(event(run, "message.delta", turn=1, text="new"))      # live text of turn 1
        stored.append(event(run, "message.completed", 4, turn=1, text="new"))
        ch.bus.publish(stored[-1])
        state["status"] = "completed"
        stored.append(event(run, "run.completed", 5))
        ch.bus.publish(stored[-1])
        ch.bus.publish_end(run)

    items = drain(ch, run, 0, page, status, publish)
    kinds = [(i.event.kind, i.event.sequence) for i in items if i.kind == "event"]
    assert kinds == [("run.started", 1), ("message.completed", 2), ("turn.started", 3),
                     ("message.delta", None), ("message.completed", 4), ("run.completed", 5)]
    assert items[0].kind == "event"  # a first connection (cursor 0) is not asked to resync


def test_pipeline_asks_a_resumed_client_to_resync_and_heals_a_missed_event():
    ch, run = build_channels(lambda: None, RunEventSettings(backend="memory", heartbeat_seconds=1.0)), uuid4()
    stored = [event(run, "run.started", 1)]
    page, state, status = make_page(stored)

    def publish():
        time.sleep(0.1)
        stored.append(event(run, "tool.started", 2))      # never published: the bus missed it
        stored.append(event(run, "tool.completed", 3))
        ch.bus.publish(stored[-1])                        # the jump from 1 to 3 triggers a database catch-up
        state["status"] = "completed"
        ch.bus.publish_end(run)

    items = drain(ch, run, 1, page, status, publish)
    assert items[0].kind == "resync"
    assert [i.event.sequence for i in items if i.kind == "event"] == [2, 3]


def test_pipeline_ends_without_the_bus_once_the_run_already_finished():
    ch, run = build_channels(lambda: None, RunEventSettings(backend="memory")), uuid4()
    stored = [event(run, "run.started", 1), event(run, "run.completed", 2)]
    page, state, status = make_page(stored)
    state["status"] = "completed"
    items = drain(ch, run, 0, page, status, lambda: None)
    assert [i.event.sequence for i in items if i.kind == "event"] == [1, 2]


# -- commit hook and worker integration ---------------------------------------------------------


def text_model(*parts):
    return FakeModel([[ModelChunk("text", text=part) for part in parts]])


def stored_kinds(factory, run_id):
    with factory() as db:
        return [row.event_type for row in db.scalars(select(RunEventRecord)
                .where(RunEventRecord.run_id == run_id).order_by(RunEventRecord.sequence))]


def test_streamed_text_stays_off_the_database_but_the_turn_text_is_stored(database):
    ch = install_channels(database, RunEventSettings(backend="memory"))
    _, _, _, run, _ = stack(database)
    run_once(database, "w", model_factory=lambda _: text_model("Hel", "lo"))
    kinds = stored_kinds(database, run.id)
    assert "message.delta" not in kinds and "message.completed" in kinds and run_row(database, run.id).status == "completed"
    with database() as db:
        completed = db.scalar(select(RunEventRecord).where(RunEventRecord.run_id == run.id,
                                                          RunEventRecord.event_type == "message.completed"))
    assert completed.payload["text"] == "Hello" and isinstance(completed.payload["turn"], int)
    items = asyncio.run(collect(ch.bus, run.id, limit=200, heartbeat=0.05))
    texts = "".join(i.payload["text"] for i in items if isinstance(i, BusEvent) and i.kind == "message.delta")
    assert texts == "Hello" and items[-1] is END
    published = [i.kind for i in items if isinstance(i, BusEvent)]
    assert "run.started" in published and "run.completed" in published


def test_database_backend_keeps_streamed_text_as_stored_events(database):
    install_channels(database, RunEventSettings(backend="database"))
    _, _, _, run, _ = stack(database)
    run_once(database, "w", model_factory=lambda _: text_model("Hello"))
    kinds = stored_kinds(database, run.id)
    assert "message.delta" in kinds and "message.completed" in kinds


def test_rolled_back_events_are_never_published(database):
    ch = install_channels(database, RunEventSettings(backend="memory"))
    _, _, _, run, _ = stack(database)
    from nexus_platform.runs.events import append_event
    before = ch.bus.tail(run.id)
    with database() as db:
        append_event(db, run.id, "ghost", {})
        db.rollback()
    assert ch.bus.tail(run.id) == before


def test_cancel_request_wakes_the_worker_through_the_control_channel(database):
    ch = install_channels(database, RunEventSettings(backend="memory"))
    principal, tenant, _, run, _ = stack(database)
    assert ch.control.wait(run.id, 0.01) is False
    with database() as db:
        request_cancel(db, principal, tenant.id, run.id)
    assert ch.control.wait(run.id, 1) is True


def test_cancelling_a_running_run_is_prompt_with_a_wake_up(database):
    install_channels(database, RunEventSettings(backend="memory", lease_check_seconds=30.0))
    principal, tenant, _, run, _ = stack(database)
    stopped_at = {}

    async def stream():
        yield ModelChunk("text", text="partial")
        with database() as db:
            request_cancel(db, principal, tenant.id, run.id)
        started = time.monotonic()
        try:
            await asyncio.sleep(20)
        finally:
            stopped_at["after"] = time.monotonic() - started

    run_once(database, "w", model_factory=lambda _: FakeModel([stream]))
    assert run_row(database, run.id).status == "cancelled"
    # The database check is 30 s apart here, so only the wake-up can explain a stop within a second.
    assert stopped_at["after"] < 2.0


# -- SSE over the memory bus --------------------------------------------------------------------


def test_sse_replays_stored_events_and_ends_for_a_finished_run(database):
    install_channels(database, RunEventSettings(backend="memory"))
    principal, tenant, _, run, _ = stack(database)
    run_once(database, "w", model_factory=lambda _: text_model("Hi"))
    app.state.session_factory = database

    def override():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override
    app.dependency_overrides[get_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            url = f"/api/v1/tenants/{tenant.id}/runs/{run.id}/events"
            with client.stream("GET", url, headers={"Accept": "text/event-stream", "Last-Event-ID": "0"}) as response:
                text = "".join(response.iter_text())
            assert "message.completed" in text and "run.completed" in text and "stream.resync" not in text
            with client.stream("GET", url, headers={"Accept": "text/event-stream", "Last-Event-ID": "2"}) as response:
                resumed = "".join(response.iter_text())
            assert resumed.startswith("event: stream.resync") and "id: 1\n" not in resumed
            trajectory = client.get(f"/api/v1/tenants/{tenant.id}/runs/{run.id}/trajectory")
            assert trajectory.status_code == 200
            records = trajectory.json()
            assert len(records) == 1
            assert records[0]["status"] == "completed"
            assert records[0]["request_snapshot"]["messages"]
            assert records[0]["response_snapshot"]["text"] == "Hi"
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


# -- database backend ---------------------------------------------------------------------------


def test_database_bus_serves_many_subscribers_from_one_poller(database):
    ch = build_channels(database, RunEventSettings(backend="database", poll_min_ms=50, poll_max_ms=100))
    _, _, _, run, _ = stack(database)
    reads = []
    original = ch.bus.read
    ch.bus.read = lambda run_id, after: (reads.append(after), original(run_id, after))[1]

    async def scenario():
        async def reader():
            got = []
            async for item in ch.bus.subscribe(run.id, after="0", heartbeat=1.0):
                if isinstance(item, BusEvent):
                    got.append(item.sequence)
                if len(got) >= 1:
                    return got

        first, second, third = await asyncio.wait_for(asyncio.gather(reader(), reader(), reader()), 5)
        assert first == second == third
        assert len(ch.bus._pollers) == 0  # the poller is gone with its last subscriber

    asyncio.run(scenario())
    assert len(reads) <= 3  # three subscribers did not each poll


# -- embedded workers ---------------------------------------------------------------------------


def test_embedded_worker_runs_a_run_and_stops_cleanly(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'embedded.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    _, _, _, run, _ = stack(factory)
    from nexus_worker.embedded import EmbeddedWorkers
    workers = EmbeddedWorkers(factory, DeploymentSettings(mode="embedded"), poll_interval=0.1, max_runs=2,
                              execution_options={"model_factory": lambda _: text_model("Hi")})
    install_channels(factory, RunEventSettings(backend="memory"))
    workers.start()
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and run_row(factory, run.id).status != "completed":
            time.sleep(0.1)
        assert run_row(factory, run.id).status == "completed"
    finally:
        workers.stop(timeout=20)
    assert workers.threads == []
    engine.dispose()


# -- live run, quotas, model limits ---------------------------------------------------------------


def test_live_run_endpoint_follows_the_marker(database):
    ch = install_channels(database, RunEventSettings(backend="memory"))
    principal, tenant, session, run, _ = stack(database)
    app.state.session_factory = database

    def override():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override
    app.dependency_overrides[get_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            url = f"/api/v1/tenants/{tenant.id}/sessions/{session.id}/live-run"
            assert client.get(url).status_code == 204
            ch.marker.claim(session.id, run.id, 60)
            body = client.get(url).json()
            assert body["run_id"] == str(run.id)
            ch.marker.clear(session.id, run.id)
            assert client.get(url).status_code == 204
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


def test_session_quotas_are_off_by_default_and_validated(deployment_config):
    from nexus_platform.runs.quotas import session_quotas
    deployment_config("")
    assert session_quotas().per_tenant is None and session_quotas().per_user is None
    deployment_config("[platform]\nmax_concurrent_sessions_per_user = 0\n")
    with pytest.raises(DeploymentConfigError):
        session_quotas()


def test_per_user_limit_refuses_a_new_session_slot_but_not_a_second_run_in_a_held_session(database, monkeypatch):
    from nexus_platform.errors import TooManyActiveSessions
    from nexus_platform.runs import admission_repository
    from nexus_platform.runs.quotas import SessionQuotas
    from nexus_platform.runs.service import create_run
    from nexus_platform.sessions.service import create_session
    principal, tenant, session, _, _ = stack(database)  # leaves one session holding work
    monkeypatch.setattr(admission_repository, "session_quotas", lambda: SessionQuotas(per_user=1))
    with database() as db:
        second = create_session(db, principal, tenant.id, agent_version_id=session.agent_version_id)
        create_run(db, principal, tenant.id, session.id, message="again", idempotency_key="k2")  # same session: allowed
        with pytest.raises(TooManyActiveSessions):
            create_run(db, principal, tenant.id, second.id, message="new session", idempotency_key="k3")


def test_model_limiter_caps_background_calls_per_model():
    from nexus_platform.runs.model_limits import ModelLimiter
    limiter = ModelLimiter(1)
    running, peak, lock = [0], [0], threading.Lock()

    def job():
        with limiter.slot("m"):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.05)
            with lock:
                running[0] -= 1

    threads = [threading.Thread(target=job) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] == 1
    other = ModelLimiter(None)
    with other.slot("m"), other.slot("m"):  # no limit configured: nothing is held back
        pass


def test_model_limit_setting_is_validated(deployment_config):
    from nexus_platform.runs.model_limits import max_background_per_model
    deployment_config("")
    assert max_background_per_model() is None
    deployment_config("[model_limits]\nmax_background_per_model = 4\n")
    assert max_background_per_model() == 4
    deployment_config("[model_limits]\nmax_background_per_model = 0\n")
    with pytest.raises(DeploymentConfigError):
        max_background_per_model()


# -- redis backend (fakeredis) --------------------------------------------------------------------


@pytest.fixture
def redis_bus():
    fakeredis = pytest.importorskip("fakeredis")
    pytest.importorskip("lupa")
    from nexus_platform.runs.bus.redis_backend import RedisBus
    server = fakeredis.FakeServer()
    sync = fakeredis.FakeRedis(server=server)
    bus = RedisBus("redis://fake", prefix="t", maxlen=64, retention_seconds=30, sync_client=sync,
                   async_client_factory=lambda: fakeredis.FakeAsyncRedis(server=server))
    yield bus
    bus.close()


def test_redis_bus_orders_replays_and_ends(redis_bus):
    run = uuid4()
    for index in range(3):
        redis_bus.publish(event(run, "message.delta", text=str(index)))
    redis_bus.publish(event(run, "run.started", 1))
    redis_bus.publish_end(run)
    items = asyncio.run(collect(redis_bus, run, limit=20))
    assert [i.payload.get("text") for i in items[:3]] == ["0", "1", "2"]
    assert items[3].sequence == 1 and items[3].kind == "run.started" and items[-1] is END
    resumed = asyncio.run(collect(redis_bus, run, after=items[1].cursor, limit=20))
    assert [i.payload.get("text") for i in resumed[:1]] == ["2"]


def test_redis_bus_reports_a_gap_when_the_window_moved_on(redis_bus):
    run = uuid4()
    for index in range(200):
        redis_bus.publish(event(run, "message.delta", text=str(index)))
    items = asyncio.run(collect(redis_bus, run, after="1-0", limit=3))
    assert isinstance(items[0], StreamGap)


def test_redis_bus_fences_ephemeral_text_to_the_current_producer(redis_bus):
    from nexus_core.run_events import BusUnavailable
    run = uuid4()
    first = redis_bus.start_producer(run, "worker-a")
    redis_bus.publish(event(run, "message.delta", text="a"))
    assert redis_bus.producer_state(run) == "active" and redis_bus.renew_producer(first)
    redis_bus._sync.set(redis_bus.producer_key(run), "someone-else")      # another worker took over
    with pytest.raises(BusUnavailable):
        redis_bus.publish(event(run, "message.delta", text="stale"))
    redis_bus.publish(event(run, "tool.started", 2))                      # stored events are fenced by the database, not here
    assert not redis_bus.renew_producer(first)
    texts = [i.payload.get("text") for i in asyncio.run(collect(redis_bus, run, limit=2)) if isinstance(i, BusEvent)]
    assert "stale" not in texts


def test_redis_bus_goes_quiet_after_a_failure_instead_of_stalling_the_producer(redis_bus):
    from nexus_core.run_events import BusUnavailable
    from redis.exceptions import ConnectionError as RedisConnectionError
    run = uuid4()

    def broken(*args, **kwargs):
        raise RedisConnectionError("down")

    redis_bus._sync.xadd = broken
    with pytest.raises(BusUnavailable):
        redis_bus.publish(event(run, "tool.started", 1))
    started = time.monotonic()
    with pytest.raises(BusUnavailable):
        redis_bus.publish(event(run, "tool.started", 2))   # skipped during back-off, no second network attempt
    assert time.monotonic() - started < 0.1


def test_redis_bus_shares_one_reader_and_backfills_a_late_joiner_without_duplicates(redis_bus):
    run = uuid4()
    for index in range(1, 6):
        redis_bus.publish(event(run, "tool.started", index))

    async def scenario():
        async def read(after, count, out, ready=None):
            async for item in redis_bus.subscribe(run, after=after, heartbeat=0.2):
                if isinstance(item, BusEvent):
                    out.append(item.sequence)
                    if ready is not None and len(out) == 5:
                        ready.set()
                if item is END or len(out) >= count:
                    return

        early, late, ready = [], [], asyncio.Event()
        first = asyncio.create_task(read(None, 7, early, ready))
        await asyncio.wait_for(ready.wait(), 3)          # the first subscriber has read all five
        second = asyncio.create_task(read(None, 7, late))   # joins from the start: events 1-5 come from the backlog
        await asyncio.sleep(0.3)
        assert len(redis_bus._readers) == 1               # one reader serves both
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: [redis_bus.publish(event(run, "tool.started", n)) for n in (6, 7)])
        await asyncio.wait_for(asyncio.gather(first, second), 5)
        return early, late

    early, late = asyncio.run(scenario())
    assert early == late == [1, 2, 3, 4, 5, 6, 7]
    assert redis_bus._readers == {}                       # the last subscriber out stopped the reader


def test_redis_bus_reader_ends_every_subscriber_at_the_end_marker(redis_bus):
    run = uuid4()

    async def scenario():
        async def read(out):
            async for item in redis_bus.subscribe(run, after=None, heartbeat=0.2):
                out.append(item)

        a, b = [], []
        tasks = [asyncio.create_task(read(a)), asyncio.create_task(read(b))]
        await asyncio.sleep(0.2)
        redis_bus.publish(event(run, "tool.started", 1))
        redis_bus.publish_end(run)
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        return a, b

    a, b = asyncio.run(scenario())
    assert a[-1] is END and b[-1] is END
    assert [i.sequence for i in a if isinstance(i, BusEvent)] == [1] == [i.sequence for i in b if isinstance(i, BusEvent)]


def test_redis_control_marker_and_limiter(redis_bus):
    from nexus_platform.runs.bus.control import RedisControl, RedisMarker
    from nexus_platform.runs.model_limits import ModelLimiter
    client, run, session = redis_bus._sync, uuid4(), uuid4()
    control = RedisControl("redis://fake", prefix="t", client=client)
    assert control.wait(run, 0.05) is False
    control.signal(run, "cancel")
    assert control.wait(run, 0.5) is True and control.wait(run, 0.05) is False
    marker = RedisMarker("redis://fake", prefix="t", client=client)
    marker.claim(session, run, 30)
    assert marker.get(session) == str(run)
    marker.clear(session, uuid4())
    assert marker.get(session) == str(run)
    marker.clear(session, run)
    assert marker.get(session) is None
    limiter = ModelLimiter(1, client, "t")
    with limiter.slot("m"):
        assert client.zcard("t:model:m:background") == 1
    assert client.zcard("t:model:m:background") == 0


def test_pipeline_over_redis_streams_matches_the_memory_behaviour(redis_bus):
    from nexus_platform.runs.bus.factory import Channels
    ch = Channels(redis_bus, MemoryControl(), MemoryMarker(), RunEventSettings(backend="redis", heartbeat_seconds=1.0))
    run = uuid4()
    stored = [event(run, "run.started", 1)]
    page, state, status = make_page(stored)

    def publish():
        time.sleep(0.1)
        redis_bus.publish(event(run, "message.delta", turn=1, text="hi"))
        stored.append(event(run, "message.completed", 2, turn=1, text="hi"))
        redis_bus.publish(stored[-1])
        state["status"] = "completed"
        redis_bus.publish_end(run)

    items = drain(ch, run, 0, page, status, publish)
    assert [(i.event.kind, i.event.sequence) for i in items if i.kind == "event"] == [
        ("run.started", 1), ("message.delta", None), ("message.completed", 2)]
