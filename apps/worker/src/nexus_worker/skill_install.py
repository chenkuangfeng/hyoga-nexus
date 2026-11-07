"""Worker job: build the dependency environments of skills being installed, and clean up after interrupted builds
(openspec 2026-11-07-skill-evolution, S3 3.7). The work itself lives in `nexus_platform.skills.install`."""
from __future__ import annotations

import logging
import time

from nexus_platform.skills import install

logger = logging.getLogger("nexus_worker.skill_install")

#: Cleanup runs about every five minutes per worker process.
REAP_INTERVAL_SECONDS = 300
_last_reap = 0.0


def skill_install_tick(factory) -> bool:
    """Build one waiting skill version (True when there was one); reap leftovers when it is time."""
    global _last_reap
    now = time.monotonic()
    if now - _last_reap >= REAP_INTERVAL_SECONDS:
        _last_reap = now
        try:
            counts = install.reap(factory)
            if any(counts.values()):
                logger.info("Skill install cleanup: %s", counts)
        except Exception:
            logger.exception("Skill install cleanup failed")
    return install.tick(factory)
