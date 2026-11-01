from __future__ import annotations

import asyncio
import argparse
import logging
import os
import signal
import socket
import threading

from nexus_platform.configuration import DatabaseConfigurationError, model_connection_pool, resolve_database_url
from nexus_runtimes.native.models.network import configure_connection_pool
from nexus_platform.persistence.database import create_database_engine, session_factory
from nexus_core.platform import utc_now
from nexus_platform.runs import session_ledger as ledger
from nexus_platform.runs.service import claim_next, process_claimed

logging.basicConfig(level=os.getenv("NEXUS_LOG_LEVEL", "INFO"))
logger = logging.getLogger("nexus_worker")


def start_process_epoch(factory, instance_id: str) -> int:
    """Begin a new process generation and mark earlier unfinished admissions ``unknown``.

    Runs once at worker startup, before any claim. Recovered runs are logged, never replayed;
    their sessions stay blocked until an operator resolves them.
    """
    with factory() as db:
        epoch = ledger.begin_process(db, instance_id=instance_id, now=utc_now())
        recovered = ledger.recover_previous_epochs(db, epoch=epoch, now=utc_now())
        db.commit()
    if recovered:
        logger.error("Unknown Run outcomes after restart; sessions blocked until resolved",
                     extra={"run_ids": [str(run_id) for run_id in recovered], "epoch": epoch})
    return epoch


#: One event loop for the worker process. Shared HTTP connection pools are bound to the loop that
#: created them, so Runs must not each create and close their own loop.
_LOOP: asyncio.AbstractEventLoop | None = None


def _worker_loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP


from nexus_worker.memory_capture import capture_tick


def run_once(factory, worker_id: str, *, stopped=None, **execution_options) -> bool:
    with factory() as session:
        task_id = claim_next(session, worker_id)
    if task_id is None:
        return False
    from nexus_worker.native import execute_native
    _worker_loop().run_until_complete(execute_native(factory, task_id, worker_id, stopped=stopped, **execution_options))
    return True


def run_worker(*, database_url: str, poll_interval: float = 1.0, once: bool = False) -> None:
    pool = model_connection_pool()
    configure_connection_pool(max_connections=pool.max_connections,
                              max_keepalive_connections=pool.max_keepalive_connections,
                              keepalive_expiry=pool.keepalive_expiry_seconds)
    engine = create_database_engine(database_url)
    factory = session_factory(engine)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stopped = threading.Event()
    epoch = start_process_epoch(factory, worker_id)

    def stop(signum, _frame):
        logger.info("Shutdown requested", extra={"signal": signum, "worker_id": worker_id})
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logger.info("Worker started", extra={"worker_id": worker_id})
    try:
        while not stopped.is_set():
            try:
                processed = run_once(factory, worker_id, stopped=stopped, ledger_epoch=epoch)
                if not processed:
                    # Memory capture runs only while no Run is waiting (stage 3); it is off unless an owner opted in.
                    processed = capture_tick(factory, worker_id)
            except Exception:
                logger.error("Worker task failed; task lease retained for recovery", extra={"worker_id": worker_id})
                processed = False
            if once:
                return
            if not processed:
                stopped.wait(poll_interval)
    finally:
        engine.dispose()
        logger.info("Worker stopped", extra={"worker_id": worker_id})


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyoga Nexus durable Run queue worker")
    parser.add_argument("--once", action="store_true", help="process at most one queued task")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()
    try:
        database_url = resolve_database_url()
    except DatabaseConfigurationError as exc:
        parser.error(str(exc))
    run_worker(database_url=database_url, poll_interval=max(0.1, args.poll_interval), once=args.once)


if __name__ == "__main__":
    main()
