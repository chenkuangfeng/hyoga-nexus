"""Unit tests for the storage-free memory rules in `nexus_memory`, using an in-memory repository."""
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from nexus_memory import service
from nexus_memory import text as memtext
from nexus_memory.ports import (DraftMeta, DraftView, EntryView, LiveEntry, MemoryConflict, MemoryNotFound, SearchRow,
                                SizedEntry, VersionView)


class FakeRepo:
    """Implements the MemoryRepository port with plain dictionaries."""

    def __init__(self):
        self.entries: dict = {}
        self.versions: dict = {}
        self.drafts: dict = {}
        self.audits: list = []
        self.tombstones: set = set()
        self.tombstone_topics: list = []

    def add_draft(self, tenant_id, owner_id, *, kind='memory', diff='fact', status='pending_review', base_version=None):
        draft = DraftView(id=uuid4(), tenant_id=tenant_id, owner_user_id=owner_id, kind=kind, diff=diff,
                          status=status, source_run_id=uuid4(), fingerprint=memtext.fingerprint(diff),
                          base_version=base_version)
        self.drafts[draft.id] = draft
        return draft

    def create_draft(self, *, tenant_id, source_run_id, kind, diff, fingerprint, base_version, origin, source_message_ids,
                     meta=None):
        meta = meta or DraftMeta()
        draft = DraftView(id=uuid4(), tenant_id=tenant_id, owner_user_id=self.run_owner, kind=kind, diff=diff,
                          status='pending_review', source_run_id=source_run_id, fingerprint=fingerprint,
                          base_version=base_version, origin=origin, source_message_ids=tuple(source_message_ids),
                          topic=meta.topic, importance=meta.importance, confidence=meta.confidence,
                          valid_until=meta.valid_until, evidence=tuple(meta.evidence),
                          annotations=dict(meta.annotations), target_entry_id=meta.target_entry_id)
        self.drafts[draft.id] = draft
        return draft.id

    run_owner = None

    def find_duplicate(self, tenant_id, owner_id, fingerprint):
        for e in self.entries.values():
            v = self.versions.get((e.id, e.current_version))
            if e.tenant_id == tenant_id and e.owner_user_id == owner_id and e.active and v and v.fingerprint == fingerprint:
                return ('entry', e.id)
        for d in self.drafts.values():
            if d.tenant_id == tenant_id and d.owner_user_id == owner_id and d.status == 'pending_review' and d.fingerprint == fingerprint:
                return ('draft', d.id)
        return None

    def is_tombstoned(self, tenant_id, owner_id, fingerprint):
        return (tenant_id, owner_id, fingerprint) in self.tombstones

    def add_tombstone(self, tenant_id, owner_id, fingerprint, topic=''):
        self.tombstones.add((tenant_id, owner_id, fingerprint))
        if topic:
            self.tombstone_topics.insert(0, (tenant_id, owner_id, topic))

    def rejected_topics(self, tenant_id, owner_id, since, limit):
        out = []
        for t, o, topic in self.tombstone_topics:
            if (t, o) == (tenant_id, owner_id) and topic not in out:
                out.append(topic)
        return out[:limit]

    def live_entries(self, tenant_id, owner_id):
        rows = [e for e in self.entries.values() if e.tenant_id == tenant_id and e.owner_user_id == owner_id and e.active]
        # Most recently changed first: later versions were appended later in these tests.
        rows.sort(key=lambda e: self.order.get(e.id, 0), reverse=True)
        return [LiveEntry(entry=e, content=getattr(self.versions.get((e.id, e.current_version)), 'content', ''))
                for e in rows]

    order: dict = {}

    def touch(self, entry_ids, now):
        for entry_id in entry_ids:
            if entry_id in self.entries:
                e = self.entries[entry_id]
                self.entries[entry_id] = replace(e, use_count=e.use_count + 1, last_used_at=now)

    def sized_entries(self, tenant_id, owner_id):
        out = []
        for e in self.entries.values():
            if e.tenant_id == tenant_id and e.owner_user_id == owner_id and e.active:
                v = self.versions[(e.id, e.current_version)]
                out.append(SizedEntry(id=e.id, title=e.title, chars=len(v.content)))
        return sorted(out, key=lambda item: item.title)

    def search(self, tenant_id, owner_id, tokens, now, limit):
        rows = []
        for e in self.entries.values():
            if e.tenant_id != tenant_id or e.owner_user_id != owner_id or not (e.active and e.enabled):
                continue
            if e.valid_until is not None and e.valid_until <= now:
                continue
            v = self.versions[(e.id, e.current_version)]
            haystack = memtext.tokenize(v.content)
            if all(f' {t} ' in f' {haystack} ' or (memtext.is_single_cjk(t) and t in v.content) for t in tokens):
                rows.append(SearchRow(entry_id=e.id, title=e.title, kind=e.kind, version=v.version,
                                      content=v.content, score=1.0, importance=e.importance,
                                      last_used_at=e.last_used_at))
        return rows[:limit]

    def published_entries(self, tenant_id, owner_id, project):
        rows = [e for e in self.entries.values() if e.tenant_id == tenant_id and e.owner_user_id == owner_id and e.active]
        if project:
            rows = [e for e in rows if e.project in ('', project)]
        return sorted(rows, key=lambda e: e.title)

    def pending_drafts(self, tenant_id, owner_id):
        return [d for d in self.drafts.values() if d.tenant_id == tenant_id and d.owner_user_id == owner_id
                and d.status == 'pending_review']

    def owned_entry(self, tenant_id, owner_id, entry_id, *, lock=False):
        e = self.entries.get(entry_id)
        if e and e.tenant_id == tenant_id and e.owner_user_id == owner_id and e.active:
            return e
        return None

    def version(self, entry_id, version):
        return self.versions.get((entry_id, version))

    def draft_for_review(self, tenant_id, draft_id):
        d = self.drafts.get(draft_id)
        return d if d and d.tenant_id == tenant_id else None

    def set_draft_status(self, draft_id, status):
        self.drafts[draft_id] = replace(self.drafts[draft_id], status=status)

    def create_entry(self, *, tenant_id, owner_id, kind, title, project, topic='', importance=3):
        e = EntryView(id=uuid4(), tenant_id=tenant_id, owner_user_id=owner_id, kind=kind, title=title,
                      project=project, active=True, current_version=1, enabled=True, valid_until=None,
                      topic=topic, importance=importance)
        self.entries[e.id] = e
        return e

    def bump_entry(self, entry_id, *, current_version, title=None, project=None, active=None,
                   enabled=None, valid_until=None, topic=None, importance=None):
        from nexus_memory.ports import UNSET
        e = self.entries[entry_id]
        self.entries[entry_id] = replace(e, current_version=current_version,
                                         topic=e.topic if topic is None else topic,
                                         importance=e.importance if importance is None else importance,
                                         title=e.title if title is None else title,
                                         project=e.project if project is None else project,
                                         active=e.active if active is None else active,
                                         enabled=e.enabled if enabled is None else enabled,
                                         valid_until=e.valid_until if valid_until is UNSET else valid_until)

    def append_version(self, *, entry_id, version, content, source_run_id, source_draft_id, reviewer_id,
                       fingerprint='', source_message_ids=()):
        self.versions[(entry_id, version)] = VersionView(entry_id, version, content, source_run_id, source_draft_id,
                                                         fingerprint, tuple(source_message_ids))
        self.counter = getattr(self, 'counter', 0) + 1
        self.order = {**self.order, entry_id: self.counter}

    def audit(self, tenant_id, actor_id, action, target_type, target_id, metadata=None):
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
        repo.create_entry(tenant_id=ws, owner_id=owner, kind='sop', title=f'Entry {i:03d} ' + 'x' * 60, project='')
    repo.create_entry(tenant_id=ws, owner_id=owner, kind='sop', title='Other', project='alpha')
    text = service.index(repo, ws, owner, 'beta')
    assert len(text) <= 6000
    assert 'Other' not in text
    assert 'Entry 000' in text
