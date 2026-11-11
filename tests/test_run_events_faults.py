"""Fault injection for the Redis run event bus against a real ``redis-server``
(openspec 2026-11-07-run-event-streaming 8.2).

Each test starts its own server on a free port and kills or restarts it, which ``fakeredis`` cannot do. The tests
are skipped when no ``redis-server`` binary is installed. What is checked is what a viewer and a Run depend on: a dead
Redis never stalls or fails a Run, viewers fall back to the database instead of hanging, and no reader or
connection outlives its subscribers.
"""
from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
from uuid import uuid4

import pytest

from nexus_core.run_events import END, BusEvent, BusUnavailable

redis = pytest.importorskip("redis")
pytestmark = pytest.mark.skipif(shutil.which("redis-server") is None, reason="redis-server is not installed")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    """A throwaway ``redis-server`` that can be killed and started again on the same port."""

    def __init__(self, tmp_path):
        self.port, self.dir, self.process = free_port(), tmp_path, None

    @property
    def url(self) -> str:
        return f"redis://127.0.0.1:{self.port}/0"

    def start(self) -> None:
        self.process = subprocess.Popen(["redis-server", "--port", str(self.port), "--bind", "127.0.0.1", "--save", "",
                                         "--appendonly", "no", "--dir", str(self.dir)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if redis.Redis.from_url(self.url).ping():
                    return
            except redis.RedisError:
                time.sleep(0.05)
        raise RuntimeError("redis-server did not start")

    def kill(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.wait(5)
            self.process = None

    def clients(self) -> int:
        return int(redis.Redis.from_url(self.url).info("clients")["connected_clients"])


@pytest.fixture
def server(tmp_path):
    instance = Server(tmp_path)
    instance.start()
    yield instance
    instance.kill()


@pytest.fixture
def bus(server):
    from nexus_platform.runs.bus.redis_backend import RedisBus
    instance = RedisBus(server.url, prefix="fault", maxlen=10_000, retention_seconds=30)
    yield instance
    instance.close()


def event(run, sequence=None, **payload):
    return BusEvent(str(run), "tool.started" if sequence is not None else "message.delta", payload, sequence)


# -- Redis dies while Runs publish --------------------------------------------------------------------


def test_publishing_never_stalls_a_run_when_redis_dies_and_resumes_when_it_returns(server, bus):
    run = uuid4()
    bus.publish(event(run, 1))
    server.kill()
    started = time.monotonic()
    with pytest.raises(BusUnavailable):
        bus.publish(event(run, 2))
    assert time.monotonic() - started < 2.0          # bounded by the socket timeout, never a hang
    started = time.monotonic()
    for sequence in range(3, 50):
        with pytest.raises(BusUnavailable):
            bus.publish(event(run, sequence))        # the breaker is open: no network attempt per event
    assert time.monotonic() - started < 0.5
    assert bus.ping() is False
    server.start()
    bus._broken_until = 0.0                          # skip the back-off window instead of waiting it out
    bus.publish(event(run, 100))
    assert bus.ping() is True


def test_a_running_viewer_is_told_the_bus_is_gone_and_a_new_one_works_after_the_restart(server, bus):
    run = uuid4()
    received, failure = [], []

    async def scenario():
        async def viewer():
            try:
                async for item in bus.subscribe(run, after=None, heartbeat=0.3):
                    if isinstance(item, BusEvent):
                        received.append(item.sequence)
            except BusUnavailable as exc:
                failure.append(exc)

        task = asyncio.create_task(viewer())
        await asyncio.sleep(0.3)
        await asyncio.to_thread(lambda: [bus.publish(event(run, n)) for n in (1, 2, 3)])
        await asyncio.sleep(0.5)
        server.kill()
        await asyncio.wait_for(task, 10)              # retries are bounded, then the viewer is released

        server.start()
        bus._broken_until = 0.0
        cursor = None
        resumed = []

        async def after_restart():
            async for item in bus.subscribe(run, after=cursor, heartbeat=0.3):
                if isinstance(item, BusEvent):
                    resumed.append(item.sequence)
                    return

        waiting = asyncio.create_task(after_restart())
        await asyncio.sleep(0.3)
        await asyncio.to_thread(bus.publish, event(run, 4))   # the stream was lost with the old server
        await asyncio.wait_for(waiting, 5)
        return resumed

    resumed = asyncio.run(scenario())
    assert received == [1, 2, 3] and len(failure) == 1
    assert resumed == [4]


# -- clients go away -----------------------------------------------------------------------------------


def test_cancelled_viewers_leave_no_reader_and_no_connection_behind(server, bus):
    runs = [uuid4() for _ in range(5)]

    async def scenario():
        async def viewer(run):
            async for _ in bus.subscribe(run, after=None, heartbeat=0.3):
                pass

        tasks = [asyncio.create_task(viewer(run)) for run in runs for _ in range(6)]   # 30 viewers, 5 Runs
        await asyncio.sleep(0.6)
        assert len(bus._readers) == 5                 # one reader per Run, not per viewer
        during = server.clients()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0.5)
        return during

    during = asyncio.run(scenario())
    assert bus._readers == {}
    assert during <= 10                                # five blocking readers plus the producer and this test's client
    assert server.clients() <= 3


def test_a_stalled_viewer_is_cut_off_without_slowing_or_starving_the_others(server, bus, monkeypatch):
    from nexus_platform.runs.bus import redis_backend
    monkeypatch.setattr(redis_backend, "_SUBSCRIBER_BACKLOG", 50)
    run, total = uuid4(), 300
    healthy, stalled_error = [], []

    async def scenario():
        async def good():
            async for item in bus.subscribe(run, after=None, heartbeat=0.3):
                if isinstance(item, BusEvent):
                    healthy.append(item.sequence)
                    if len(healthy) == total:
                        return

        stall = asyncio.Event()

        async def stalled():
            generator = bus.subscribe(run, after=None, heartbeat=0.3)
            await generator.__anext__()                # attached, then it stops reading (a frozen connection)
            await stall.wait()
            try:
                while True:
                    await generator.__anext__()
            except BusUnavailable as exc:
                stalled_error.append(exc)

        tasks = [asyncio.create_task(good()), asyncio.create_task(stalled())]
        await asyncio.sleep(0.5)
        await asyncio.to_thread(lambda: [bus.publish(event(run, n)) for n in range(1, total + 1)])
        await asyncio.wait_for(tasks[0], 10)           # the healthy viewer got every event
        stall.set()
        await asyncio.wait_for(tasks[1], 10)

    asyncio.run(scenario())
    assert healthy == list(range(1, total + 1))
    assert len(stalled_error) == 1                     # told to fall back to the database, not left hanging


# -- the worker goes away ------------------------------------------------------------------------------


def test_a_vanished_worker_is_detected_and_its_successor_fences_it_out(server, bus, monkeypatch):
    from nexus_platform.runs.bus import redis_backend
    monkeypatch.setattr(redis_backend, "PRODUCER_LEASE_SECONDS", 1)
    run = uuid4()
    first = bus.start_producer(run, "worker-a")
    bus.publish(event(run, None, text="a"))
    assert bus.producer_state(run) == "active"
    time.sleep(1.4)                                     # worker-a never renewed: it crashed
    assert bus.producer_state(run) == "expired"        # the stream is there, the lease is not: viewers fall back
    assert bus.renew_producer(first) is False
    second = bus.start_producer(run, "worker-b")       # lease recovery handed the Run to another worker
    bus._tokens[str(run)] = first.token                # a zombie worker-a that wakes up and keeps streaming text
    with pytest.raises(BusUnavailable):
        bus.publish(event(run, None, text="from the zombie"))
    bus._tokens[str(run)] = second.token
    bus.publish(event(run, None, text="from worker-b"))
    texts = []

    async def read():
        async for item in bus.subscribe(run, after=None, heartbeat=0.2):
            if isinstance(item, BusEvent):
                texts.append(item.payload["text"])
            if len(texts) == 2:
                return

    asyncio.run(asyncio.wait_for(read(), 5))
    assert texts == ["a", "from worker-b"]


def test_the_end_marker_reaches_every_viewer_and_the_stream_then_expires(server, bus):
    run = uuid4()
    bus.retention = 1

    async def scenario():
        async def viewer(out):
            async for item in bus.subscribe(run, after=None, heartbeat=0.3):
                out.append(item)

        a, b = [], []
        tasks = [asyncio.create_task(viewer(a)), asyncio.create_task(viewer(b))]
        await asyncio.sleep(0.4)
        await asyncio.to_thread(lambda: (bus.publish(event(run, 1)), bus.publish_end(run)))
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        return a, b

    a, b = asyncio.run(scenario())
    assert a[-1] is END and b[-1] is END
    time.sleep(1.5)
    assert redis.Redis.from_url(server.url).exists(bus.stream_key(run)) == 0
