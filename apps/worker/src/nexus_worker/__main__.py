from __future__ import annotations

import asyncio
import argparse
import logging
import os
import signal
import socket
import threading

from nexus_platform.configuration import DatabaseConfigurationError, logging_level, model_connection_pool, resolve_database_url, watchdog_settings
from nexus_runtimes.native.models.network import configure_connection_pool
from nexus_platform.persistence.database import create_database_engine, session_factory
from nexus_core.platform import utc_now
from nexus_platform.runs import session_ledger as ledger
from nexus_platform.runs.service import claim_next, process_claimed

logging.basicConfig(level=logging_level())
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


from nexus_worker.memory_capture import (capture_tick, consolidation_tick, embedding_tick, install_embedder,
                                         retention_tick)
from nexus_worker import knowledge_index


def run_once(factory, worker_id: str, *, stopped=None, **execution_options) -> bool:
    with factory() as session:
        task_id = claim_next(session, worker_id)
    if task_id is None:
        return False
    from nexus_worker.native import execute_native
    _worker_loop().run_until_complete(execute_native(factory, task_id, worker_id, stopped=stopped, **execution_options))
    # Stage 6 (D6): a space's external memory provider observes the finished turn in the background.
    from nexus_platform.memory.providers import after_run
    from nexus_platform.persistence.models import OutboxRecord
    with factory() as session:
        task = session.get(OutboxRecord, task_id)
        run_id = task.run_id if task is not None else None
    if run_id is not None:
        after_run(factory, run_id)
    return True


def run_worker(*, database_url: str, poll_interval: float = 1.0, once: bool = False) -> None:
    pool = model_connection_pool()
    # Read before any Run starts: an invalid [watchdog] section stops the worker instead of silently changing behaviour.
    watchdog = watchdog_settings()
    configure_connection_pool(max_connections=pool.max_connections,
                              max_keepalive_connections=pool.max_keepalive_connections,
                              keepalive_expiry=pool.keepalive_expiry_seconds)
    engine = create_database_engine(database_url)
    factory = session_factory(engine)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    install_embedder()
    knowledge_index.install_embedder()
    # Read before work starts: an invalid [knowledge] section stops the worker.
    from nexus_platform.configuration import knowledge_settings
    knowledge_concurrency = knowledge_settings().index_concurrency
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
                processed = run_once(factory, worker_id, stopped=stopped, ledger_epoch=epoch, watchdog=watchdog)
                if not processed:
                    # Scheduled tasks that are due start their Runs here (openspec 2026-11-07-tool-expansion 8.2).
                    from .schedule import schedule_tick
                    processed = schedule_tick(factory)
                if not processed:
                    # Knowledge index and cleanup jobs (openspec 2026-11-06-knowledge-base K1.5).
                    processed = knowledge_index.knowledge_tick(factory, _worker_loop(), knowledge_concurrency)
                if not processed:
                    # Memory capture runs only while no Run is waiting (stage 3); it is off unless an owner opted in.
                    processed = capture_tick(factory, worker_id)
                if not processed:
                    # Consolidation (one owner per tick) and retention (hourly) are maintenance: idle time only.
                    processed = consolidation_tick(factory, worker_id)
                    retention_tick(factory)
                if not processed:
                    processed = embedding_tick(factory, _worker_loop()) > 0
            except Exception:
                logger.error("Worker task failed; task lease retained for recovery", extra={"worker_id": worker_id}, exc_info=True)
                processed = False
            if once:
                return
            if not processed:
                stopped.wait(poll_interval)
    finally:
        engine.dispose()
        logger.info("Worker stopped", extra={"worker_id": worker_id})


def _sandbox_check() -> int:
    """Run the isolation acceptance against `[sandbox]` and print each item. Returns the process exit code."""
    import asyncio
    import json
    from nexus_core.deployment import DeploymentConfigError
    from nexus_core.sandbox import SandboxError
    from nexus_sandbox import acceptance
    from nexus_sandbox.settings import load_settings
    try:
        report = asyncio.run(acceptance.run(load_settings()))
    except (DeploymentConfigError, SandboxError) as error:
        print(f"sandbox check not run: {getattr(error, 'code', error)}")
        return 2
    for item in report["items"]:
        print(f"{'PASS' if item['ok'] else 'FAIL'}  {item['name']}: {item['detail']}")
    print(json.dumps({"passed": report["passed"], "report": str(acceptance.report_path(load_settings()))}))
    return 0 if report["passed"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyoga Nexus durable Run queue worker")
    parser.add_argument("--once", action="store_true", help="process at most one queued task")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--sandbox-check", action="store_true",
                        help="run the sandbox isolation acceptance, store the report and exit (0 = passed)")
    args = parser.parse_args()
    if args.sandbox_check:
        raise SystemExit(_sandbox_check())
    try:
        database_url = resolve_database_url()
    except DatabaseConfigurationError as exc:
        parser.error(str(exc))
    run_worker(database_url=database_url, poll_interval=max(0.1, args.poll_interval), once=args.once)


if __name__ == "__main__":
    main()
