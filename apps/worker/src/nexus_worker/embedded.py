"""Worker threads inside the API process (``[deployment].mode = "embedded"``).

Same loop as the standalone worker (``run_loop``), started from the API's lifespan. One worker executes one
Run at a time, so ``embedded_workers`` threads let that many Runs execute at once; only the first thread also
does the idle-time jobs, capped by ``background_concurrency``. Events travel over the in-process memory bus.
A thread that dies is restarted after a pause, so a bug in one Run cannot take the API down with it.
"""
from __future__ import annotations

import logging
import os
import socket
import threading

from nexus_platform.configuration import watchdog_settings
from nexus_platform.runs.bus import DeploymentSettings, install_channels

logger = logging.getLogger("nexus_worker.embedded")
RESTART_PAUSE_SECONDS = 5.0


class EmbeddedWorkers:
    """Start and stop the worker threads of one API process."""

    def __init__(self, factory, settings: DeploymentSettings, poll_interval: float = 1.0) -> None:
        self.factory, self.settings, self.poll_interval = factory, settings, max(0.1, poll_interval)
        self.stopped = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        from nexus_worker.__main__ import install_embedder, knowledge_index, start_process_epoch
        watchdog = watchdog_settings()  # an invalid [watchdog] stops start-up, as for the standalone worker
        install_channels(self.factory)
        install_embedder()
        knowledge_index.install_embedder()
        base = f"{socket.gethostname()}:{os.getpid()}"
        epoch = start_process_epoch(self.factory, base)
        for index in range(self.settings.embedded_workers):
            thread = threading.Thread(
                target=self._supervise, name=f"nexus-embedded-worker-{index}", daemon=True,
                args=(f"{base}:{index}", epoch, watchdog, index == 0))
            thread.start()
            self.threads.append(thread)
        logger.info("Embedded workers started", extra={"workers": len(self.threads)})

    def _supervise(self, worker_id: str, epoch: int, watchdog, background: bool) -> None:
        from nexus_worker.__main__ import run_loop
        while not self.stopped.is_set():
            try:
                run_loop(self.factory, worker_id, self.stopped, epoch=epoch, watchdog=watchdog,
                         poll_interval=self.poll_interval, background=background,
                         knowledge_concurrency=self.settings.background_concurrency)
                return
            except Exception:
                logger.error("Embedded worker stopped unexpectedly; restarting", extra={"worker_id": worker_id}, exc_info=True)
                self.stopped.wait(RESTART_PAUSE_SECONDS)

    def stop(self, timeout: float = 30.0) -> None:
        """Ask every thread to stop and wait up to ``timeout`` seconds in total for them to finish."""
        self.stopped.set()
        for thread in self.threads:
            thread.join(timeout=max(0.1, timeout / max(1, len(self.threads))))
        alive = [thread.name for thread in self.threads if thread.is_alive()]
        if alive:
            logger.warning("Embedded workers still running after the stop timeout", extra={"threads": alive})
        self.threads.clear()
