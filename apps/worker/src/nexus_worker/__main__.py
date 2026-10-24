from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading

from nexus_platform.persistence.database import create_database_engine, session_factory
from nexus_platform.runs.service import claim_next, process_claimed

logging.basicConfig(level=os.getenv("NEXUS_LOG_LEVEL", "INFO"))
logger = logging.getLogger("nexus_worker")


def run_once(factory, worker_id: str) -> bool:
    with factory() as session:
        task_id = claim_next(session, worker_id)
    if task_id is None:
        return False
    with factory() as session:
        process_claimed(session, task_id, worker_id)
    return True


def run_worker(*, database_url: str, poll_interval: float = 1.0, once: bool = False) -> None:
    engine = create_database_engine(database_url)
    factory = session_factory(engine)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stopped = threading.Event()

    def stop(signum, _frame):
        logger.info("Shutdown requested", extra={"signal": signum, "worker_id": worker_id})
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logger.info("Worker started", extra={"worker_id": worker_id})
    try:
        while not stopped.is_set():
            try:
                processed = run_once(factory, worker_id)
            except Exception:
                logger.exception("Worker task failed", extra={"worker_id": worker_id})
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
    database_url = os.getenv("NEXUS_DATABASE_URL")
    if not database_url:
        parser.error("NEXUS_DATABASE_URL must be configured")
    run_worker(database_url=database_url, poll_interval=max(0.1, args.poll_interval), once=args.once)


if __name__ == "__main__":
    main()
