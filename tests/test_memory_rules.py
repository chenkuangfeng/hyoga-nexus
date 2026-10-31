"""Unit tests for the storage-free memory rules in `nexus_memory`, using an in-memory repository."""
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from nexus_memory import service
from nexus_memory.ports import DraftView, EntryView, MemoryConflict, MemoryNotFound, VersionView


class FakeRepo:
    """Implements the MemoryRepository port with plain dictionaries."""

    def __init__(self):
        self.entries: dict = {}
        self.versions: dict = {}
        self.drafts: dict = {}
        self.audits: list = []

    def add_draft(self, workspace_id, owner_id, *, kind='memory', diff='fact', status='pending_review'):
        draft = DraftView(id=uuid4(), workspace_id=workspace_id, owner_user_id=owner_id, kind=kind, diff=diff,
                          status=status, source_run_id=uuid4())
        self.drafts[draft.id] = draft
        return draft

    def published_entries(self, workspace_id, owner_id, project):
        rows = [e for e in self.entries.values() if e.workspace_id == workspace_id and e.owner_user_id == owner_id and e.active]
        if project:
            rows = [e for e in rows if e.project in ('', project)]
        return sorted(rows, key=lambda e: e.title)

    def pending_drafts(self, workspace_id, owner_id):
        return [d for d in self.drafts.values() if d.workspace_id == workspace_id and d.owner_user_id == owner_id
                and d.status == 'pending_review']

    def owned_entry(self, workspace_id, owner_id, entry_id, *, lock=False):
        e = self.entries.get(entry_id)
        if e and e.workspace_id == workspace_id and e.owner_user_id == owner_id and e.active:
            return e
        return None

    def version(self, entry_id, version):
        return self.versions.get((entry_id, version))

    def draft_for_review(self, workspace_id, draft_id):
        d = self.drafts.get(draft_id)
        return d if d and d.workspace_id == workspace_id else None

    def set_draft_status(self, draft_id, status):
        self.drafts[draft_id] = replace(self.drafts[draft_id], status=status)

    def create_entry(self, *, workspace_id, owner_id, kind, title, project):
        e = EntryView(id=uuid4(), workspace_id=workspace_id, owner_user_id=owner_id, kind=kind, title=title,
                      project=project, active=True, current_version=1)
        self.entries[e.id] = e
        return e

    def bump_entry(self, entry_id, *, current_version, title=None, project=None, active=None):
        e = self.entries[entry_id]
        self.entries[entry_id] = replace(e, current_version=current_version,
                                         title=e.title if title is None else title,
                                         project=e.project if project is None else project,
                                         active=e.active if active is None else active)

    def append_version(self, *, entry_id, version, content, source_run_id, source_draft_id, reviewer_id):
        self.versions[(entry_id, version)] = VersionView(entry_id, version, content, source_run_id, source_draft_id)

    def audit(self, workspace_id, actor_id, action, target_type, target_id, metadata=None):
        self.audits.append((action, target_id))


@pytest.fixture
def world():
    repo = FakeRepo()
    ws, owner = uuid4(), uuid4()
    return repo, ws, owner


def test_review_publishes_new_entry_at_version_one_and_marks_draft(world):
    repo, ws, owner = world
    draft = repo.add_draft(ws, owner, diff='use checklist')
    result = service.review(repo, owner, ws, draft.id, approve=True, title='  Checklist ')
    assert result['status'] == 'published' and result['version'] == 1
    assert repo.drafts[draft.id].status == 'approved'
    assert repo.entries[UUID(result['id'])].title == 'Checklist'
    assert ('memory.published', result['id']) in repo.audits


def test_review_rejects_foreign_draft_as_not_found(world):
    repo, ws, owner = world
    draft = repo.add_draft(ws, uuid4())
    with pytest.raises(MemoryNotFound, match='Draft unavailable'):
        service.review(repo, owner, ws, draft.id, approve=True, title='x')


def test_review_cannot_run_twice(world):
    repo, ws, owner = world
    draft = repo.add_draft(ws, owner)
    service.review(repo, owner, ws, draft.id, approve=False, title='')
    with pytest.raises(MemoryConflict, match='already reviewed'):
        service.review(repo, owner, ws, draft.id, approve=True, title='x')


def test_review_edit_checks_optimistic_version_and_kind(world):
    repo, ws, owner = world
    first = service.review(repo, owner, ws, repo.add_draft(ws, owner).id, approve=True, title='A')
    entry_id = UUID(first['id'])
    stale = repo.add_draft(ws, owner, kind='memory')
    with pytest.raises(MemoryConflict):
        service.review(repo, owner, ws, stale.id, approve=True, title='A', entry_id=entry_id, expected_version=0)
    sop = repo.add_draft(ws, owner, kind='sop')
    with pytest.raises(MemoryConflict, match='kind mismatch'):
        service.review(repo, owner, ws, sop.id, approve=True, title='A', entry_id=entry_id, expected_version=1)


def test_title_is_validated_only_when_approving(world):
    repo, ws, owner = world
    draft = repo.add_draft(ws, owner)
    with pytest.raises(ValueError):
        service.review(repo, owner, ws, draft.id, approve=True, title='   ')
    assert service.review(repo, owner, ws, draft.id, approve=False, title='')['status'] == 'rejected'


def test_read_version_zero_means_current_and_missing_version_is_not_found(world):
    repo, ws, owner = world
    first = service.review(repo, owner, ws, repo.add_draft(ws, owner, diff='v1').id, approve=True, title='A')
    entry_id = UUID(first['id'])
    assert service.read(repo, owner, ws, entry_id)['content'] == 'v1'
    with pytest.raises(MemoryNotFound, match='version unavailable'):
        service.read(repo, owner, ws, entry_id, version=9)


def test_restore_appends_and_archive_hides_entry(world):
    repo, ws, owner = world
    first = service.review(repo, owner, ws, repo.add_draft(ws, owner, diff='v1').id, approve=True, title='A')
    entry_id = UUID(first['id'])
    edit = service.review(repo, owner, ws, repo.add_draft(ws, owner, diff='v2').id, approve=True, title='A',
                          entry_id=entry_id, expected_version=1)
    assert edit['version'] == 2
    restored = service.restore(repo, owner, ws, entry_id, version=1, expected_version=2)
    assert restored['version'] == 3
    assert repo.versions[(entry_id, 3)].content == 'v1'
    with pytest.raises(MemoryConflict):
        service.restore(repo, owner, ws, entry_id, version=1, expected_version=2)
    service.archive(repo, owner, ws, entry_id)
    with pytest.raises(MemoryNotFound, match='unavailable'):
        service.read(repo, owner, ws, entry_id)


def test_index_is_bounded_and_respects_project_filter(world):
    repo, ws, owner = world
    for i in range(200):
        repo.create_entry(workspace_id=ws, owner_id=owner, kind='sop', title=f'Entry {i:03d} ' + 'x' * 60, project='')
    repo.create_entry(workspace_id=ws, owner_id=owner, kind='sop', title='Other', project='alpha')
    text = service.index(repo, ws, owner, 'beta')
    assert len(text) <= 6000
    assert 'Other' not in text
    assert 'Entry 000' in text
