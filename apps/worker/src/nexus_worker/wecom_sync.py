"""WeCom directory sync in the worker (openspec 2026-11-11-enterprise-saas E3).

Every enterprise bound to a WeCom corp is synced once a day, and soon after an administrator or a directory
callback asks for it (``sync_status = 'requested'``). The tick checks at most once a minute per process and syncs
one enterprise per call so other idle-time jobs keep running. Failures are recorded on the corp by the service.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)
_LAST_CHECK: list[float] = []
_API = None


def _api():
    global _API
    if _API is None:
        from nexus_connectors.wecom.client import HttpWeComApi
        _API = HttpWeComApi()
    return _API


def wecom_tick(factory: sessionmaker[Session], *, api=None, interval_seconds: float = 60.0) -> bool:
    """Sync the first enterprise that is due; True when one was synced (or failed trying)."""
    from nexus_platform.wecom import service
    from nexus_platform.wecom.client import WeComError
    now = time.monotonic()
    if _LAST_CHECK and now - _LAST_CHECK[0] < interval_seconds:
        return False
    _LAST_CHECK[:] = [now]
    with factory() as db, db.begin():
        due = service.due_for_sync(db)
    for tenant_id in due:
        with factory() as db:
            try:
                stats = service.sync_directory(db, api or _api(), tenant_id)
                logger.info('WeCom directory synced', extra={'tenant_id': str(tenant_id), **stats})
            except WeComError:
                logger.warning('WeCom directory sync failed', extra={'tenant_id': str(tenant_id)}, exc_info=True)
            except Exception:  # an enterprise without apps, or a configuration error: try the next one
                logger.warning('WeCom directory sync skipped', extra={'tenant_id': str(tenant_id)}, exc_info=True)
                continue
        return True
    return False
