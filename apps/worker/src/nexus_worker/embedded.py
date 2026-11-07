"""The worker inside the API process (``[deployment].mode = "embedded"``).

One thread runs one event loop (``run_async``), and that loop executes up to ``[worker].max_concurrent_runs``
Runs as coroutines, so there is no thread per Run and the model connection pool is shared by all of them.
The worker has an engine and connection pool of its own, apart from the API's, so a burst of API requests
cannot starve a Run's heartbeat. Events travel over the in-process memory bus. If the loop dies it is started
again after a pause, so a bug in one Run cannot take the API down with it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading

from nexus_platform.configuration import watchdog_settings
from nexus_platform.runs.bus import DeploymentSettings, install_channels
from nexus_platform.runs.dbexec import configure_db_executor, shutdown_db_executor
from nexus_platform.runs.worker_settings import WorkerSettings

logger = logging.getLogger("nexus_worker.embedded")
RESTART_PAUSE_SECONDS = 5.0


class EmbeddedWorkers:
    """Start and stop the worker thread of one API process."""

    def __init__(self, factory, settings: DeploymentSettings, worker: WorkerSettings | None = None,
                 poll_interval: float = 1.0, max_runs: int | None = None, execution_options: dict | None = None) -> None:
        self.factory, self.settings = factory, settings
        self.worker = worker or WorkerSettings()
        self.max_runs = max_runs if max_runs is not None else self.worker.max_concurrent_runs
        self.poll_interval = max(0.1, poll_interval)
        self.execution_options = execution_options or {}  # passed to every Run (tests inject a model here)
        self.stopped = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        from nexus_worker.__main__ import install_embedder, knowledge_index, start_process_epoch
        watchdog = watchdog_settings()  # an invalid [watchdog] stops start-up, as for the standalone worker
        install_channels(self.factory)
        install_embedder()
        knowledge_index.install_embedder()
        worker_id = f"{socket.gethostname()}:{os.getpid()}:embedded"
        epoch = start_process_epoch(self.factory, worker_id)
        configure_db_executor(self.worker.db_threads)
        thread = threading.Thread(target=self._supervise, name="nexus-embedded-worker", daemon=True,
                                  args=(worker_id, epoch, watchdog))
        thread.start()
        self.threads.append(thread)
        logger.info("Embedded worker started", extra={"max_concurrent_runs": self.max_runs})

    def _supervise(self, worker_id: str, epoch: int, watchdog) -> None:
        from nexus_worker.__main__ import run_async
        while not self.stopped.is_set():
            try:
                asyncio.run(run_async(
                    self.factory, worker_id, self.stopped, epoch=epoch, watchdog=watchdog, max_runs=self.max_runs,
                    poll_interval=self.poll_interval, knowledge_concurrency=self.settings.background_concurrency,
                    background_concurrency=self.settings.background_concurrency,
                    stop_timeout=self.worker.stop_timeout_seconds, execution_options=self.execution_options))
                return
            except Exception:
                logger.error("Embedded worker stopped unexpectedly; restarting", extra={"worker_id": worker_id}, exc_info=True)
                self.stopped.wait(RESTART_PAUSE_SECONDS)

    def stop(self, timeout: float = 30.0) -> None:
        """Ask the worker to stop and wait up to ``timeout`` seconds for it to wind its Runs down."""
        self.stopped.set()
        for thread in self.threads:
            thread.join(timeout=max(0.1, timeout))
        alive = [thread.name for thread in self.threads if thread.is_alive()]
        if alive:
            logger.warning("Embedded worker still running after the stop timeout", extra={"threads": alive})
        self.threads.clear()
        shutdown_db_executor()
