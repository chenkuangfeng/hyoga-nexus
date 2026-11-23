from __future__ import annotations

import asyncio
import argparse
import logging
import os
import signal
import socket
import threading
import time

from nexus_platform.configuration import DatabaseConfigurationError, logging_level, model_connection_pool, resolve_database_url, watchdog_settings
from nexus_runtimes.native.models.network import configure_connection_pool
from nexus_platform.persistence.database import create_database_engine, session_factory
from nexus_core.platform import utc_now
from nexus_platform.runs import session_ledger as ledger
from nexus_platform.runs import unknown
from nexus_tools.builtins.registration import side_effects_by_name
from nexus_platform.runs.bus import install_channels
from nexus_platform.runs.dbexec import configure_db_executor, run_db, shutdown_db_executor
from nexus_platform.runs.worker_settings import worker_settings
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
        # Scheduled tasks have nobody to ask whether to resend, and an operator may allow clearing the Runs that
        # provably left nothing half-done; every other block waits for a person (openspec 2026-11-07-worker-concurrency).
        with factory() as db:
            cleared = unknown.settle_unattended(db)
            if unknown.auto_resolve_safe_unknown():
                cleared += unknown.settle_safe(db, side_effects_by_name())
            db.commit()
        waiting = [run_id for run_id in recovered if run_id not in set(cleared)]
        logger.error("Unknown Run outcomes after restart; %d sessions cleared automatically, %d blocked until resolved",
                     len(cleared), len(waiting), extra={"run_ids": [str(run_id) for run_id in waiting], "epoch": epoch})
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
        _record_usage(factory, run_id)
    return True


def sandbox_startup_check(factory) -> list[str]:
    """Log a warning for every docker or bwrap sandbox profile without a valid acceptance report; returns their names.

    Read-only: it never runs the probes (they exhaust memory and processes on purpose, and several workers starting
    together would race), so an operator runs `--sandbox-check` once. Until then the `sandbox` tool group stays
    unavailable for agents using that profile. Never raises: a broken `[sandbox]` section or database only skips the check.
    """
    try:
        from nexus_core.deployment import DeploymentConfigError
        from nexus_platform.runs.sandbox_acceptance import DbReportStore
        from nexus_sandbox import acceptance
        from nexus_sandbox.settings import load_config
        try:
            config = load_config()
        except DeploymentConfigError:
            return []  # reported when a Run asks for the sandbox; not a reason to stop the worker
        if not config.enabled:
            return []
        missing = []
        with factory() as db:
            store = DbReportStore(db)
            for settings in config.profiles.values():
                if settings.backend != "local" and not acceptance.passed(settings, store):
                    missing.append(settings.profile)
        if missing:
            logger.warning("Sandbox profiles without a passing acceptance report: %s; run "
                           "`python -m nexus_worker --sandbox-check` (agents on them cannot use the sandbox tools until then)",
                           ", ".join(missing))
        return missing
    except Exception:
        logger.warning("Sandbox startup check skipped", exc_info=True)
        return []


def run_worker(*, database_url: str, poll_interval: float = 1.0, once: bool = False) -> None:
    pool = model_connection_pool()
    # Read before any Run starts: an invalid [watchdog] section stops the worker instead of silently changing behaviour.
    watchdog = watchdog_settings()
    configure_connection_pool(max_connections=pool.max_connections,
                              max_keepalive_connections=pool.max_keepalive_connections,
                              keepalive_expiry=pool.keepalive_expiry_seconds)
    # Read before any Run starts: an invalid [worker] section stops the worker.
    settings = worker_settings()
    engine = create_database_engine(database_url, pool_size=settings.pool_size)
    factory = session_factory(engine)
    try:
        # Builtin tools live under the system space; register any added since the last start.
        from nexus_platform.system import ensure_system_resources
        with factory() as session:
            ensure_system_resources(session)
    except Exception:
        logger.exception("System space sync failed; builtin tools may be unavailable until it succeeds")
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    sandbox_startup_check(factory)
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
        if once:
            # One pass of the synchronous loop: what tests and `--once` rely on.
            run_loop(factory, worker_id, stopped, epoch=epoch, watchdog=watchdog, poll_interval=poll_interval,
                     once=True, knowledge_concurrency=knowledge_concurrency)
        else:
            configure_db_executor(settings.db_threads)
            runs = settings.effective_runs(database_url)
            if runs < settings.max_concurrent_runs:
                logger.warning("SQLite has a single writer: running %d Runs at once instead of the configured %d",
                               runs, settings.max_concurrent_runs)
            asyncio.run(run_async(factory, worker_id, stopped, epoch=epoch, watchdog=watchdog, max_runs=runs,
                                  poll_interval=poll_interval, knowledge_concurrency=knowledge_concurrency,
                                  stop_timeout=settings.stop_timeout_seconds))
    finally:
        shutdown_db_executor()
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
                # Dependency builds of skills being installed, and cleanup of interrupted ones (skill-evolution S3).
                from .skill_install import skill_install_tick
                processed = skill_install_tick(factory)
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
            if background:
                # Idle and orphaned sandbox containers (openspec 2026-11-07-tool-expansion 3.3); on the loop that ran the Runs.
                from .sandbox_runtime import reap_if_due
                reap_if_due(_worker_loop())
        except Exception:
            logger.error("Worker task failed; task lease retained for recovery", extra={"worker_id": worker_id}, exc_info=True)
            processed = False
        if once:
            return
        if not processed:
            stopped.wait(poll_interval)


def _record_usage(factory, run_id) -> None:
    """E6: add an ended Run's tokens to the usage ledger; a Run still waiting is added later by usage_tick."""
    from nexus_platform.usage.service import record_run_usage
    try:
        with factory() as session, session.begin():
            record_run_usage(session, run_id)
    except Exception:
        logger.warning("Recording run usage failed", extra={"run_id": str(run_id)}, exc_info=True)


_LAST_GOVERNANCE_RETENTION: list[float] = []


def governance_retention_tick(factory, *, interval_seconds: float = 3600.0) -> None:
    """E7: purge sessions past their enterprise's retention period, at most hourly per process."""
    import time
    from nexus_platform.governance.retention import run_retention
    now = time.monotonic()
    if _LAST_GOVERNANCE_RETENTION and now - _LAST_GOVERNANCE_RETENTION[0] < interval_seconds:
        return
    _LAST_GOVERNANCE_RETENTION[:] = [now]
    try:
        with factory() as session:
            stats = run_retention(session)
        if stats:
            logger.info("Retention purged sessions", extra={"purged": stats})
    except Exception:
        logger.warning("Retention failed", exc_info=True)


def usage_tick(factory) -> bool:
    """Add ended Runs the after-run hook missed to the usage ledger (E6); True when any was added."""
    from nexus_platform.usage.service import record_run_usage, unrecorded_runs
    with factory() as session, session.begin():
        added = [run_id for run_id in unrecorded_runs(session, limit=50) if record_run_usage(session, run_id)]
    return bool(added)


def _background_pass(factory, worker_id: str, knowledge_concurrency: int) -> bool:
    """One pass over the idle-time jobs; True when any did work. Runs on the background thread.

    Each job keeps its synchronous implementation (some use ``asyncio.run`` or this thread's own event loop),
    so it runs in a thread of its own and never on the loop that executes Runs.
    """
    from .schedule import schedule_tick
    if schedule_tick(factory):
        return True
    from .wecom_sync import wecom_tick
    if wecom_tick(factory):
        return True
    from .channels import delivery_tick
    if delivery_tick(factory):
        return True
    if usage_tick(factory):
        return True
    governance_retention_tick(factory)
    if knowledge_index.knowledge_tick(factory, _worker_loop(), knowledge_concurrency):
        return True
    if capture_tick(factory, worker_id):
        return True
    if consolidation_tick(factory, worker_id):
        retention_tick(factory)
        return True
    retention_tick(factory)
    return embedding_tick(factory, _worker_loop()) > 0


def _claim_task(factory, worker_id: str):
    with factory() as session:
        return claim_next(session, worker_id)


def _after_run(factory, task_id) -> None:
    # Stage 6 (D6): a space's external memory provider observes the finished turn in the background.
    from nexus_platform.memory.providers import after_run
    from nexus_platform.persistence.models import OutboxRecord
    with factory() as session:
        task = session.get(OutboxRecord, task_id)
        run_id = task.run_id if task is not None else None
    if run_id is not None:
        after_run(factory, run_id)
        _record_usage(factory, run_id)


#: Seconds between measurements of how late the event loop runs; a Run's lease lasts 60 s.
LOOP_LAG_INTERVAL = 1.0
LOOP_LAG_WARN_SECONDS = 1.0


async def _watch_loop_lag(stopped: threading.Event, active) -> None:
    """Warn when the loop is held up, which delays every Run's heartbeat. Observes only; never touches a Run."""
    while not stopped.is_set():
        started = time.monotonic()
        await asyncio.sleep(LOOP_LAG_INTERVAL)
        lag = time.monotonic() - started - LOOP_LAG_INTERVAL
        if lag > LOOP_LAG_WARN_SECONDS:
            logger.warning("Worker event loop ran %.1f s late with %d Runs active: a synchronous call is blocking it",
                           lag, len(active))


async def run_async(factory, worker_id: str, stopped: threading.Event, *, epoch: int, watchdog, max_runs: int,
                    poll_interval: float = 1.0, knowledge_concurrency: int = 1, background: bool = True,
                    background_concurrency: int = 1, stop_timeout: float = 30.0, execution_options=None) -> None:
    """Claim and execute Runs concurrently on this event loop until ``stopped`` is set.

    At most ``max_runs`` Runs execute at once. A claim is made only when a slot is free, so the worker never
    holds a lease on a Run it is not executing. Synchronous database calls go to the database pool; the idle-time
    jobs run on a thread of their own. On stop no new Run is claimed and the running ones are asked to stop
    (they finish as interrupted); any still running after ``stop_timeout`` are left to lease recovery.
    """
    from concurrent.futures import ThreadPoolExecutor
    from nexus_worker.native import execute_native
    options = execution_options or {}
    slots = asyncio.Semaphore(max_runs)
    active: set[asyncio.Task] = set()
    background_tasks: set[asyncio.Task] = set()
    background_pool = ThreadPoolExecutor(max_workers=max(1, background_concurrency), thread_name_prefix="nexus-bg")
    loop = asyncio.get_running_loop()

    async def execute(task_id) -> None:
        try:
            await execute_native(factory, task_id, worker_id, stopped=stopped, ledger_epoch=epoch,
                                 watchdog=watchdog, **options)
            await run_db(_after_run, factory, task_id)
        except Exception:
            logger.error("Run failed outside its own handling; its lease is left to recovery",
                         extra={"worker_id": worker_id}, exc_info=True)
        finally:
            slots.release()

    async def idle_pass() -> None:
        try:
            await loop.run_in_executor(background_pool, _background_pass, factory, worker_id, knowledge_concurrency)
        except Exception:
            logger.error("Background job failed", extra={"worker_id": worker_id}, exc_info=True)

    lag_task = asyncio.create_task(_watch_loop_lag(stopped, active))
    from .sandbox_runtime import reap_periodically
    reap_task = asyncio.create_task(reap_periodically(stopped)) if background else None
    from .channels import wechat_poller
    wechat_task = asyncio.create_task(wechat_poller(factory, stopped, worker_id)) if background else None
    logger.info("Worker accepting Runs", extra={"worker_id": worker_id, "max_concurrent_runs": max_runs})
    try:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(slots.acquire(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            try:
                task_id = await run_db(_claim_task, factory, worker_id)
            except Exception:
                slots.release()
                logger.error("Claiming work failed", extra={"worker_id": worker_id}, exc_info=True)
                await asyncio.sleep(poll_interval)
                continue
            if task_id is None:
                slots.release()
                background_tasks.difference_update({t for t in background_tasks if t.done()})
                if background and len(background_tasks) < max(1, background_concurrency):
                    task = asyncio.create_task(idle_pass())
                    background_tasks.add(task)
                waited = 0.0
                while waited < poll_interval and not stopped.is_set():
                    await asyncio.sleep(0.1)
                    waited += 0.1
                continue
            task = asyncio.create_task(execute(task_id))
            active.add(task)
            task.add_done_callback(active.discard)
    finally:
        stopped.set()  # Run monitors watch this event and cancel their Runs
        if active:
            _, pending = await asyncio.wait(set(active), timeout=stop_timeout)
            if pending:
                logger.warning("%d Runs still running after the stop timeout; their leases will expire", len(pending))
        lag_task.cancel()
        if reap_task is not None:
            reap_task.cancel()
        if wechat_task is not None:
            wechat_task.cancel()
        if background_tasks:
            await asyncio.wait(set(background_tasks), timeout=5)
        background_pool.shutdown(wait=False)
        logger.info("Worker stopped accepting Runs", extra={"worker_id": worker_id})


def _run_acceptance(settings) -> dict:
    """Run the acceptance of one profile and store the report in the platform database (the file copy is always
    written). Without a usable database configuration only the file is written, which a single-host deployment
    still reads; the missing database is reported once on stderr."""
    import sys
    from nexus_sandbox import acceptance
    try:
        database_url = resolve_database_url()
    except DatabaseConfigurationError as exc:
        print(f"database not configured, the report is saved as a file only: {exc}", file=sys.stderr)
        return asyncio.run(acceptance.run(settings))
    from nexus_platform.runs.sandbox_acceptance import DbReportStore
    engine = create_database_engine(database_url)
    try:
        # The session connects only when the report is saved, so no connection is held while the probes run.
        with session_factory(engine)() as db:
            report = asyncio.run(acceptance.run(settings, store=DbReportStore(db)))
            db.commit()
        return report
    finally:
        engine.dispose()


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
        print("sandbox check not run: no isolating profile is defined")
        return 2
    exit_code = 0
    for settings in chosen:
        print(f"== profile {settings.profile} ({settings.backend})")
        try:
            report = _run_acceptance(settings)
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
