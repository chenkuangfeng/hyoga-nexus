"""Memory rules: bounded index, owner-scoped reads, draft review and append-only versions.

Source behavior: GenericAgent memory_management_sop.md and start_long_term_update,
plus WeKnora engine memory injection. Approval replaces direct shared-file mutation;
raw Run history remains the L4 provenance and is not rewritten during consolidation.

Functions here assume the caller has already resolved the acting user and opened a
transaction. They never commit. Denials are raised as `MemoryNotFound` / `MemoryConflict`.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .ports import EntryView, MemoryConflict, MemoryNotFound, MemoryRepository, VersionView

INDEX_LIMIT = 6000
TITLE_LIMIT = 160


def index(repo: MemoryRepository, workspace_id: UUID, owner_id: UUID, project: str = '') -> str:
    """Produce a bounded pointer index; facts/SOP bodies are read on demand by ID."""
    rows = repo.published_entries(workspace_id, owner_id, project)
    return '\n'.join(f'{row.id} | {row.kind} | {row.title} | v{row.current_version}' for row in rows)[:INDEX_LIMIT]


def list_memory(repo: MemoryRepository, owner_id: UUID, workspace_id: UUID) -> dict[str, Any]:
    """List published entries and the owner's pending drafts."""
    published = [{'id': str(row.id), 'title': row.title, 'kind': row.kind, 'project': row.project,
                  'version': row.current_version} for row in repo.published_entries(workspace_id, owner_id, '')]
    drafts = [{'id': str(d.id), 'kind': d.kind, 'diff': d.diff, 'source_run_id': str(d.source_run_id)}
              for d in repo.pending_drafts(workspace_id, owner_id)]
    return {'entries': published, 'drafts': drafts}


def read(repo: MemoryRepository, owner_id: UUID, workspace_id: UUID, entry_id: UUID,
         version: int | None = None) -> dict[str, Any]:
    """Return an owned published version with source Run/Draft metadata; version 0/None means current."""
    entry = _owned(repo, workspace_id, owner_id, entry_id)
    selected = _version(repo, entry.id, version or entry.current_version)
    repo.audit(workspace_id, owner_id, 'memory.read', 'memory', str(entry.id), {'version': selected.version})
    return {'id': str(entry.id), 'title': entry.title, 'kind': entry.kind, 'content': selected.content,
            'version': selected.version, 'source_run_id': str(selected.source_run_id)}


def read_for_run(repo: MemoryRepository, workspace_id: UUID, owner_id: UUID, entry_id: UUID,
                 run_id: UUID) -> str:
    """Return the current published content for a model tool call, audited against the run."""
    entry = _owned(repo, workspace_id, owner_id, entry_id)
    selected = _version(repo, entry.id, entry.current_version)
    repo.audit(workspace_id, owner_id, 'memory.read', 'memory', str(entry_id),
               {'run_id': str(run_id), 'version': selected.version})
    return selected.content


def review(repo: MemoryRepository, owner_id: UUID, workspace_id: UUID, draft_id: UUID, *, approve: bool,
           title: str, entry_id: UUID | None = None, expected_version: int = 0, project: str = '') -> dict[str, Any]:
    """Publish or reject a draft owned by `owner_id`; edits always append a version.

    The user reviews the actual diff and its source. No model callback can invoke this
    function. A selected existing entry must match the optimistic version.
    """
    if approve and (not title.strip() or len(title) > TITLE_LIMIT or len(project) > TITLE_LIMIT):
        raise ValueError('Memory title/project is invalid')
    draft = repo.draft_for_review(workspace_id, draft_id)
    if not draft or draft.owner_user_id != owner_id:
        raise MemoryNotFound('Draft unavailable')
    if draft.status != 'pending_review':
        raise MemoryConflict('Draft already reviewed')
    if not approve:
        repo.set_draft_status(draft.id, 'rejected')
        repo.audit(workspace_id, owner_id, 'memory.rejected', 'memory_draft', str(draft.id))
        return {'status': 'rejected'}
    if entry_id:
        entry = _owned(repo, workspace_id, owner_id, entry_id, lock=True)
        if entry.current_version != expected_version or entry.kind != draft.kind:
            raise MemoryConflict('Memory changed or kind mismatch')
        new_version = entry.current_version + 1
        repo.bump_entry(entry.id, current_version=new_version, title=title.strip(), project=project)
        target = entry.id
    else:
        new_version = 1
        created = repo.create_entry(workspace_id=workspace_id, owner_id=owner_id, kind=draft.kind,
                                    title=title.strip(), project=project)
        target = created.id
    repo.append_version(entry_id=target, version=new_version, content=draft.diff, source_run_id=draft.source_run_id,
                        source_draft_id=draft.id, reviewer_id=owner_id)
    repo.set_draft_status(draft.id, 'approved')
    repo.audit(workspace_id, owner_id, 'memory.published', 'memory', str(target),
               {'version': new_version, 'draft_id': str(draft.id)})
    return {'status': 'published', 'id': str(target), 'version': new_version}


def archive(repo: MemoryRepository, owner_id: UUID, workspace_id: UUID, entry_id: UUID) -> None:
    """Remove an entry from navigation and future prompts while keeping immutable history."""
    entry = _owned(repo, workspace_id, owner_id, entry_id)
    repo.bump_entry(entry.id, current_version=entry.current_version, active=False)
    repo.audit(workspace_id, owner_id, 'memory.archived', 'memory', str(entry.id))


def restore(repo: MemoryRepository, owner_id: UUID, workspace_id: UUID, entry_id: UUID, version: int,
            expected_version: int) -> dict[str, Any]:
    """Restore a historical version by appending a new one; never erase intervening versions."""
    entry = _owned(repo, workspace_id, owner_id, entry_id, lock=True)
    old = _version(repo, entry.id, version)
    if entry.current_version != expected_version:
        raise MemoryConflict('Memory changed')
    new_version = entry.current_version + 1
    repo.bump_entry(entry.id, current_version=new_version)
    repo.append_version(entry_id=entry.id, version=new_version, content=old.content,
                        source_run_id=old.source_run_id, source_draft_id=old.source_draft_id, reviewer_id=owner_id)
    repo.audit(workspace_id, owner_id, 'memory.restored', 'memory', str(entry.id), {'version': new_version})
    return {'version': new_version}


def _owned(repo: MemoryRepository, workspace_id: UUID, owner_id: UUID, entry_id: UUID, *, lock: bool = False) -> EntryView:
    """Absent, foreign and archived entries share one response."""
    entry = repo.owned_entry(workspace_id, owner_id, entry_id, lock=lock)
    if entry is None:
        raise MemoryNotFound('Memory unavailable')
    return entry


def _version(repo: MemoryRepository, entry_id: UUID, version: int) -> VersionView:
    found = repo.version(entry_id, version)
    if found is None:
        raise MemoryNotFound('Memory version unavailable')
    return found
