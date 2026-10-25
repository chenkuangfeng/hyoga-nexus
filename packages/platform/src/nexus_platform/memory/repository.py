"""Scoped published-memory queries; no knowledge documents or supplier objects live here."""
from sqlalchemy import select
from nexus_platform.persistence.models import MemoryEntryRecord, MemoryVersionRecord
from nexus_platform.errors import NotFound


def entries(db, workspace_id, user_id, project: str = ''):
    """Return active private facts/SOPs for this workspace/project, never unreviewed drafts."""
    query = select(MemoryEntryRecord).where(MemoryEntryRecord.workspace_id == workspace_id,
        MemoryEntryRecord.owner_user_id == user_id, MemoryEntryRecord.active.is_(True))
    if project:
        query = query.where(MemoryEntryRecord.project.in_(['', project]))
    return list(db.scalars(query.order_by(MemoryEntryRecord.title)))


def authorized_entry(db, workspace_id, user_id, entry_id):
    """Mask absent, foreign and archived entries with the same NotFound response."""
    row = db.get(MemoryEntryRecord, entry_id)
    if not row or not row.active or row.workspace_id != workspace_id or row.owner_user_id != user_id:
        raise NotFound('Memory unavailable')
    return row


def content(db, entry):
    """Read the immutable current published version, preserving source provenance."""
    return db.get(MemoryVersionRecord, (entry.id, entry.current_version))
