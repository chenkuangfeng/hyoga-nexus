"""Worker side of scheduled runs (openspec 2026-11-07-tool-expansion, section 8.2).

`ScheduleBridge` is what `cronjob_*` tools call during a Run: it runs the platform service in a worker thread
(the service uses blocking database sessions) as the Run's owner, on the agent version of the Run's session.
`schedule_tick` fires due jobs from the worker's idle loop.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from nexus_platform.persistence.models import SessionRecord
from nexus_platform.schedule import service
from nexus_platform.schedule.rules import ScheduleError

logger = logging.getLogger("nexus_worker.schedule")


class ScheduleBridge:
    """Scheduling for one Run. Every call re-resolves the owner, so revoked membership stops it."""

    def __init__(self, factory, principal, tenant_id: UUID, session_id: UUID):
        self.factory, self.principal, self.tenant_id, self.session_id = factory, principal, tenant_id, session_id

    def _agent_version(self) -> UUID:
        with self.factory() as db:
            row = db.get(SessionRecord, self.session_id)
            if row is None:
                raise ScheduleError('schedule_unavailable', 'the conversation could not be found')
            return row.agent_version_id

    async def list(self) -> list[dict]:
        def work():
            with self.factory() as db:
                return service.list_jobs(db, self.principal, self.tenant_id)
        return await asyncio.to_thread(work)

    async def create(self, name: str, prompt: str, rule: dict, timezone_name: str) -> dict:
        def work():
            with self.factory() as db:
                return service.create_job(db, self.principal, self.tenant_id, agent_version_id=self._agent_version(),
                                          name=name, prompt=prompt, rule=rule, timezone_name=timezone_name)
        return await asyncio.to_thread(work)

    async def change(self, job_id: str, action: str) -> dict:
        def work():
            with self.factory() as db:
                return service.change_state(db, self.principal, self.tenant_id, job_id, action)
        return await asyncio.to_thread(work)


def schedule_tick(factory) -> bool:
    """Fire due jobs. True when any were handled, so the worker keeps polling quickly. Never raises."""
    try:
        return service.fire_due(factory) > 0
    except Exception:
        logger.warning("Scheduled task tick failed", exc_info=True)
        return False
