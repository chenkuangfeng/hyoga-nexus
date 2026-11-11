"""Database store of sandbox acceptance reports (openspec 2026-11-07-tool-expansion 3.6, design 2.3.1).

Implements `nexus_sandbox.acceptance.ReportStore` on the `sandbox_acceptance` table, one row per profile. The
caller owns the session: `load` only reads, `save` replaces the row and flushes, and the caller commits.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from nexus_platform.persistence.models import SandboxAcceptanceRecord


def _checked_at(report: dict) -> datetime:
    """The report's `checked_at` (UTC, `%Y-%m-%dT%H:%M:%SZ`); now when it is missing or malformed."""
    try:
        return datetime.strptime(report['checked_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return datetime.now(timezone.utc)


class DbReportStore:
    """Acceptance reports in the platform database, shared by the API and every worker."""

    def __init__(self, db: Session):
        self.db = db

    def load(self, settings) -> dict | None:
        """The profile's stored report in the shape `acceptance.run` produced, or None when it has no row."""
        # A savepoint, so a failed read cannot leave the caller's transaction unusable (PostgreSQL aborts it).
        with self.db.begin_nested():
            row = self.db.get(SandboxAcceptanceRecord, settings.profile)
        if row is None:
            return None
        return {'passed': row.passed, 'fingerprint': row.fingerprint, 'backend': row.backend,
                'checked_at': row.checked_at.strftime('%Y-%m-%dT%H:%M:%SZ'), 'items': list(row.items)}

    def save(self, settings, report: dict) -> None:
        """Replace the profile's row with `report`. Does not commit."""
        row = self.db.get(SandboxAcceptanceRecord, settings.profile)
        if row is None:
            row = SandboxAcceptanceRecord(profile=settings.profile)
            self.db.add(row)
        row.backend = report.get('backend', settings.backend)
        row.fingerprint = report['fingerprint']
        row.passed = bool(report['passed'])
        row.items = list(report.get('items', []))
        row.checked_at = _checked_at(report)
        self.db.flush()
