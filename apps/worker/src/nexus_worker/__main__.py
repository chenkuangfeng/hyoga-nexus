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
from nexus_platform.runs.bus import install_channels
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
_LOOP = threading.local()


def _worker_loop() -> asyncio.AbstractEventLoop:
    """This thread's event loop; embedded deployments run several worker threads in one process."""
    loop = getattr(_LOOP, "loop", None)
    if loop is None or loop.is_closed():
        loop = _LOOP.loop = asyncio.new_event_loop()
    return loop


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
    try:
        # Builtin tools live under the system space; register any added since the last start.
        from nexus_platform.system import ensure_system_resources
        with factory() as session:
            ensure_system_resources(session)
    except Exception:
        logger.exception("System space sync failed; builtin tools may be unavailable until it succeeds")
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
        install_channels(factory)
        run_loop(factory, worker_id, stopped, epoch=epoch, watchdog=watchdog, poll_interval=poll_interval, once=once,
                 knowledge_concurrency=knowledge_concurrency)
    finally:
        engine.dispose()
        logger.info("Worker stopped", extra={"worker_id": worker_id})


def run_loop(factory, worker_id: str, stopped: threading.Event, *, epoch: int, watchdog, poll_interval: float = 1.0,
             once: bool = False, background: bool = True, knowledge_concurrency: int = 1) -> None:
    """Claim and run work until ``stopped`` is set. Installs no signal handlers, so it can run in a thread.

    ``background`` turns the idle-time jobs (schedules, knowledge index, memory capture, consolidation,
    embeddings) on or off; an embedded deployment runs them from one thread only.
    """
    while not stopped.is_set():
        try:
            processed = run_once(factory, worker_id, stopped=stopped, ledger_epoch=epoch, watchdog=watchdog)
            if background and not processed:
                # Scheduled tasks that are due start their Runs here (openspec 2026-11-07-tool-expansion 8.2).
                from .schedule import schedule_tick
                processed = schedule_tick(factory)
            if background and not processed:
                # Knowledge index and cleanup jobs (openspec 2026-11-06-knowledge-base K1.5).
                processed = knowledge_index.knowledge_tick(factory, _worker_loop(), knowledge_concurrency)
            if background and not processed:
                # Memory capture runs only while no Run is waiting (stage 3); it is off unless an owner opted in.
                processed = capture_tick(factory, worker_id)
            if background and not processed:
                # Consolidation (one owner per tick) and retention (hourly) are maintenance: idle time only.
                processed = consolidation_tick(factory, worker_id)
                retention_tick(factory)
            if background and not processed:
                processed = embedding_tick(factory, _worker_loop()) > 0
        except Exception:
            logger.error("Worker task failed; task lease retained for recovery", extra={"worker_id": worker_id}, exc_info=True)
            processed = False
        if once:
            return
        if not processed:
            stopped.wait(poll_interval)


def _sandbox_check(profile: str | None = None) -> int:
    """Run the isolation acceptance against `[sandbox]` profiles and print each item. Returns the process exit code.

    With a profile name only that profile is checked; without one every profile that can be accepted is checked
    (`local` profiles never are: they are not an isolation boundary). Exit 0 means every checked profile passed.
    """
    import asyncio
    import json
    from nexus_core.deployment import DeploymentConfigError
    from nexus_core.sandbox import SandboxError
    from nexus_sandbox import acceptance
    from nexus_sandbox.settings import load_config
    try:
        config = load_config()
    except DeploymentConfigError as error:
        print(f"sandbox check not run: {error}")
        return 2
    if profile is not None:
        chosen = [config.get(profile)] if config.get(profile) is not None else []
        if not chosen:
            print("sandbox check not run: no such profile")
            return 2
    else:
        chosen = [item for item in config.profiles.values() if item.backend != "local"]
    if not chosen:
        print("sandbox check not run: no docker or bwrap profile is defined")
        return 2
    exit_code = 0
    for settings in chosen:
        print(f"== profile {settings.profile} ({settings.backend})")
        try:
            report = asyncio.run(acceptance.run(settings))
        except SandboxError as error:
            print(f"sandbox check not run: {getattr(error, 'code', error)}")
            exit_code = max(exit_code, 2)
            continue
        for item in report["items"]:
            print(f"{'PASS' if item['ok'] else 'FAIL'}  {item['name']}: {item['detail']}")
        print(json.dumps({"profile": settings.profile, "passed": report["passed"],
                          "report": str(acceptance.report_path(settings))}))
        if not report["passed"]:
            exit_code = max(exit_code, 1)
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyoga Nexus durable Run queue worker")
    parser.add_argument("--once", action="store_true", help="process at most one queued task")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--sandbox-check", action="store_true",
                        help="run the sandbox isolation acceptance, store the report and exit (0 = passed)")
    parser.add_argument("--profile", default=None,
                        help="with --sandbox-check: check only this profile (default: every docker and bwrap profile)")
    args = parser.parse_args()
    if args.sandbox_check:
        raise SystemExit(_sandbox_check(args.profile))
    try:
        database_url = resolve_database_url()
    except DatabaseConfigurationError as exc:
        parser.error(str(exc))
    run_worker(database_url=database_url, poll_interval=max(0.1, args.poll_interval), once=args.once)


if __name__ == "__main__":
    main()
