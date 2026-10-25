"""GA L1/L2/L3 memory navigation with reviewed publication and immutable version history.

Source behavior: GenericAgent memory_management_sop.md and start_long_term_update,
plus WeKnora engine memory injection. Approval replaces direct shared-file mutation;
raw Run history remains the L4 provenance and is not rewritten during consolidation.
"""
from uuid import UUID
from sqlalchemy import select
from nexus_core.platform import new_id, utc_now
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import MemoryDraftRecord, MemoryEntryRecord, MemoryVersionRecord, RunRecord, SessionRecord, ToolInvocationRecord
from nexus_platform.errors import NotFound, Conflict
from nexus_platform.workspaces.service import audit
from .repository import entries, authorized_entry, content


def index(db, workspace_id, user_id, project='') -> str:
    """Produce a bounded pointer index; facts/SOP bodies are read on demand by ID."""
    return '\n'.join(f'{row.id} | {row.kind} | {row.title} | v{row.current_version}'
                     for row in entries(db, workspace_id, user_id, project))[:6000]


def list_memory(db, principal, workspace_id):
    """List published entries and owned pending drafts, preserving isolation for administrators."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        published = [{'id': str(row.id), 'title': row.title, 'kind': row.kind, 'project': row.project,
                      'version': row.current_version} for row in entries(db, workspace_id, user.id)]
        drafts = db.scalars(select(MemoryDraftRecord).join(RunRecord, RunRecord.id == MemoryDraftRecord.source_run_id).where(
            MemoryDraftRecord.workspace_id == workspace_id, RunRecord.principal_id == user.id,
            MemoryDraftRecord.status == 'pending_review').order_by(MemoryDraftRecord.created_at))
        return {'entries': published, 'drafts': [{'id': str(d.id), 'kind': d.kind, 'diff': d.diff,
            'source_run_id': str(d.source_run_id)} for d in drafts]}


def read(db, principal, workspace_id, entry_id, version=None):
    """Return an owned published version with source Run/Draft and reviewer metadata."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        entry = authorized_entry(db, workspace_id, user.id, entry_id)
        selected = db.get(MemoryVersionRecord, (entry.id, version or entry.current_version))
        if not selected:
            raise NotFound('Memory version unavailable')
        audit(db, workspace_id, user.id, 'memory.read', 'memory', str(entry.id), {'version': selected.version})
        return {'id': str(entry.id), 'title': entry.title, 'kind': entry.kind, 'content': selected.content,
                'version': selected.version, 'source_run_id': str(selected.source_run_id)}


def review(db, principal, workspace_id, draft_id, *, approve: bool, title: str, entry_id=None, expected_version=0, project=''):
    """Publish/reject a draft only for its owner; edits/rollback always append a version.

    The user reviews the actual diff and its source. No model callback can invoke this
    management service. A selected existing entry must match the optimistic version.
    """
    if approve and (not title.strip() or len(title) > 160 or len(project) > 160):
        raise ValueError('Memory title/project is invalid')
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        draft = db.scalar(select(MemoryDraftRecord).where(MemoryDraftRecord.id == draft_id).with_for_update())
        run = db.get(RunRecord, draft.source_run_id) if draft else None
        if not draft or not run or draft.workspace_id != workspace_id or run.principal_id != user.id:
            raise NotFound('Draft unavailable')
        if draft.status != 'pending_review':
            raise Conflict('Draft already reviewed')
        if not approve:
            draft.status = 'rejected'
            audit(db, workspace_id, user.id, 'memory.rejected', 'memory_draft', str(draft.id))
            return {'status': 'rejected'}
        if entry_id:
            entry = authorized_entry(db, workspace_id, user.id, entry_id)
            db.refresh(entry, with_for_update=True)
            if entry.current_version != expected_version or entry.kind != draft.kind:
                raise Conflict('Memory changed or kind mismatch')
            entry.current_version += 1; entry.title = title.strip(); entry.project = project
        else:
            entry = MemoryEntryRecord(id=new_id(), workspace_id=workspace_id, owner_user_id=user.id,
                kind=draft.kind, title=title.strip(), project=project, active=True, current_version=1, created_at=utc_now())
            db.add(entry); db.flush()
        db.add(MemoryVersionRecord(entry_id=entry.id, version=entry.current_version, content=draft.diff,
            source_run_id=run.id, source_draft_id=draft.id, reviewed_by=user.id, created_at=utc_now()))
        draft.status = 'approved'
        audit(db, workspace_id, user.id, 'memory.published', 'memory', str(entry.id), {'version': entry.current_version, 'draft_id': str(draft.id)})
        return {'status': 'published', 'id': str(entry.id), 'version': entry.current_version}


def archive(db, principal, workspace_id, entry_id):
    """Remove an entry from navigation/future prompts while retaining immutable source history."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        entry = authorized_entry(db, workspace_id, user.id, entry_id)
        entry.active = False
        audit(db, workspace_id, user.id, 'memory.archived', 'memory', str(entry.id))


def restore(db, principal, workspace_id, entry_id, version: int, expected_version: int):
    """Restore a historical version by appending a new one; never erase intervening versions."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        entry = authorized_entry(db, workspace_id, user.id, entry_id)
        db.refresh(entry, with_for_update=True)
        old = db.get(MemoryVersionRecord, (entry.id, version))
        if not old:
            raise NotFound('Memory version unavailable')
        if entry.current_version != expected_version:
            raise Conflict('Memory changed')
        entry.current_version += 1
        db.add(MemoryVersionRecord(entry_id=entry.id, version=entry.current_version, content=old.content,
            source_run_id=old.source_run_id, source_draft_id=old.source_draft_id, reviewed_by=user.id, created_at=utc_now()))
        audit(db, workspace_id, user.id, 'memory.restored', 'memory', str(entry.id), {'version': entry.current_version})
        return {'version': entry.current_version}
