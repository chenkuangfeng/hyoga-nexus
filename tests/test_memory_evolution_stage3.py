"""Memory evolution stage 3: de-duplication and maintenance (openspec 2026-11-06-memory-evolution, C1-C4).

Rules: similar-entry hints, consolidation clusters and answer validation, merge drafts that archive the
other entries on publication, stale entries ranking lower. Platform: requested and background passes with
a scripted merger, request refusals, retention, migration.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from nexus_core.platform import utc_now
from nexus_memory import consolidate
from nexus_memory import service
from nexus_memory.ports import MemoryConflict
from nexus_platform.errors import Conflict
from nexus_platform.memory import consolidation
from nexus_platform.memory.repository import SqlMemoryRepository
from nexus_platform.memory.retention import run_retention
from nexus_platform.persistence.models import (
    MemoryCaptureJobRecord,
    MemoryConsolidationStateRecord,
    MemoryDraftRecord,
    MemoryEntryRecord,
)

from test_memory_capture import _enable
from test_memory_rules import FakeRepo
from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def world():
    repo = FakeRepo()
    ws, owner = uuid4(), uuid4()
    repo.run_owner = owner
    return repo, ws, owner


def _publish(repo, ws, owner, diff, *, title, kind='memory', importance=None):
    outcome = service.propose(repo, ws, owner, uuid4(), kind, diff, importance=importance)
    assert outcome['status'] == 'pending', outcome
    return service.review(repo, owner, ws, UUID(outcome['id']), approve=True, title=title)['id']


# ---------------------------------------------------------------- rules

def test_a_paraphrase_gets_a_similar_hint_and_is_still_created(world):
    repo, ws, owner = world
    entry = _publish(repo, ws, owner, '部署前必须执行发布检查清单并通知运维', title='部署')
    outcome = service.propose(repo, ws, owner, uuid4(), 'memory', '部署前必须执行发布检查清单，并提前通知运维值班')
    assert outcome['status'] == 'pending'
    assert outcome['annotations']['similar'][0]['entry_id'] == entry
    assert outcome['annotations']['similar'][0]['score'] >= service.SIMILAR_OVERLAP


def test_clusters_group_overlapping_entries_of_one_kind_strongest_first(world):
    repo, ws, owner = world
    for text, kind in (('用户偏好使用 Python 写后端服务', 'memory'), ('用户偏好使用 Python 写后端', 'memory'),
                       ('用户偏好使用 Python 写后端服务', 'sop'), ('周报每周五下午发送给团队', 'memory'),
                       ('周报每周五下午发给团队', 'memory'), ('代码缩进使用四个空格', 'memory')):
        _publish(repo, ws, owner, text + f' {uuid4().hex[:4]}', title=text[:6], kind=kind)
    found = consolidate.clusters(repo.live_entries(ws, owner), overlap=0.45, max_clusters=3)
    assert [sorted(item.entry.kind for item in cluster.entries) for cluster in found] == [['memory', 'memory']] * 2
    assert all(len(cluster.entries) == 2 for cluster in found)
    assert consolidate.clusters(repo.live_entries(ws, owner), overlap=0.45, max_clusters=1)[0].score == found[0].score
    ids = {str(item.entry.id) for item in found[0].entries}
    rest = consolidate.clusters(repo.live_entries(ws, owner), overlap=0.45, max_clusters=3, exclude=frozenset(ids))
    assert len(rest) == 1


def test_merge_answers_are_validated():
    assert consolidate.validate_merge({'merged': ' 合并 ', 'keep': 1}, 2) == consolidate.MergeDecision('合并', 1)
    for bad in ({'merged': '', 'keep': 0}, {'merged': 'x', 'keep': 2}, {'merged': 'x', 'keep': True}, [], None):
        assert consolidate.validate_merge(bad, 2) is None


def test_merge_draft_publication_edits_the_kept_entry_and_archives_the_rest(world):
    repo, ws, owner = world
    keep = _publish(repo, ws, owner, '偏好 Python', title='语言', importance=2)
    other = _publish(repo, ws, owner, '后端用 Python', title='后端', importance=4)
    live = {str(item.entry.id): item for item in repo.live_entries(ws, owner)}
    outcome = service.propose_merge(repo, ws, owner, keep=live[keep], others=[live[other]], merged='偏好用 Python 写后端')
    draft = repo.drafts[UUID(outcome['id'])]
    assert draft.origin == 'background' and draft.target_entry_id == UUID(keep) and draft.importance == 4
    assert service.merge_targets(repo, ws, owner) == frozenset({keep, other})
    published = service.review(repo, owner, ws, draft.id, approve=True, title='语言')
    assert published == {'status': 'published', 'id': keep, 'version': 2}
    assert repo.entries[UUID(other)].active is False and repo.entries[UUID(keep)].importance == 4


def test_merge_is_refused_when_a_merged_entry_changed_and_rejection_leaves_entries_alone(world):
    repo, ws, owner = world
    keep = _publish(repo, ws, owner, 'fact one about builds', title='A')
    other = _publish(repo, ws, owner, 'fact two about deploys', title='B')
    live = {str(item.entry.id): item for item in repo.live_entries(ws, owner)}
    first = service.propose_merge(repo, ws, owner, keep=live[keep], others=[live[other]], merged='merged builds and deploys')
    second = service.propose_merge(repo, ws, owner, keep=live[keep], others=[live[other]], merged='another merge text')
    edit = service.propose(repo, ws, owner, uuid4(), 'memory', 'fact two about deploys, revised', entry_id=UUID(other),
                           base_version=1)
    service.review(repo, owner, ws, UUID(edit['id']), approve=True, title='B')
    with pytest.raises(MemoryConflict):
        service.review(repo, owner, ws, UUID(first['id']), approve=True, title='A')
    service.review(repo, owner, ws, UUID(second['id']), approve=False, title='')
    assert repo.entries[UUID(keep)].active and repo.entries[UUID(other)].active
    # Changed entries are skipped when the merge is proposed, not only when it is reviewed.
    assert service.propose_merge(repo, ws, owner, keep=live[keep], others=[live[other]], merged='x y z') == {
        'status': 'skipped', 'reason': 'changed'}


def test_entries_unused_for_45_days_rank_one_step_lower(world):
    repo, ws, owner = world
    old = _publish(repo, ws, owner, 'old but important', title='Old', importance=4)
    fresh = _publish(repo, ws, owner, 'fresh normal', title='Fresh', importance=3)
    repo.touch([UUID(old)], NOW - timedelta(days=60))
    repo.touch([UUID(fresh)], NOW)
    titles = lambda: [line.split(' | ')[2] for line in service.index(repo, ws, owner, now=NOW).split('\n')]
    # Old drops from 4 to 3 and ties with Fresh, which was used more recently.
    assert titles() == ['Fresh', 'Old']
    # A validity end exempts an entry from the stale step.
    service.set_availability(repo, owner, ws, UUID(old), valid_until=NOW + timedelta(days=30))
    assert titles() == ['Old', 'Fresh']


# ---------------------------------------------------------------- platform

def _publish_db(factory, run, text, *, title):
    with factory() as db, db.begin():
        repo = SqlMemoryRepository(db)
        outcome = service.propose(repo, run.tenant_id, run.principal_id, run.id, 'memory', text)
        return service.review(repo, run.principal_id, run.tenant_id, UUID(outcome['id']), approve=True, title=title)['id']


def _seed(factory, run):
    texts = ['用户偏好使用 Python 写后端服务', '用户偏好用 Python 写后端服务程序', '周报每周五下午发送给团队',
             '代码缩进使用四个空格', '生产库是 PostgreSQL 16', '部署走蓝绿发布']
    return [_publish_db(factory, run, text, title=text[:6]) for text in texts]


def _merger(answer):
    calls = []

    def merger(*, entries, model_version_id, tenant_id, owner_id):
        calls.append([e['title'] for e in entries])
        return answer(entries) if callable(answer) else answer
    merger.calls = calls
    return merger


def test_background_pass_records_a_merge_draft_once_a_day(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    ids = _seed(database, run)
    _enable(database, principal, tenant.id)
    merger = _merger({'merged': '用户偏好用 Python 写后端服务', 'keep': 0})
    assert consolidation.consolidation_tick(database, merger, worker_id='w1') is True
    assert len(merger.calls) == 1 and len(merger.calls[0]) == 2
    with database() as db:
        draft = db.scalar(select(MemoryDraftRecord).where(MemoryDraftRecord.origin == 'background'))
        assert str(draft.target_entry_id) in ids[:2] and len(draft.annotations['merge']['archive']) == 1
        state = db.get(MemoryConsolidationStateRecord, (tenant.id, run.principal_id))
        assert state.last_run_at is not None and state.lease_owner is None
    # Not due again within a day, and the pending merge keeps its entries out of later passes.
    assert consolidation.consolidation_tick(database, merger, worker_id='w1') is False
    assert consolidation.consolidation_tick(database, merger, worker_id='w1', now=utc_now() + timedelta(days=2)) is True
    assert len(merger.calls) == 1


def test_requested_pass_runs_without_automatic_capture_and_refuses_repeats(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _seed(database, run)
    with database() as db, pytest.raises(Conflict, match='capture_model_required'):
        consolidation.request_consolidation(db, principal, tenant.id)
    _enable(database, principal, tenant.id)
    from nexus_platform.memory import capture
    with database() as db:  # automatic capture off, model kept
        settings = capture.capture_settings(db, principal, tenant.id)
    with database() as db, db.begin():
        from nexus_platform.persistence.models import MemoryCaptureSettingsRecord
        db.get(MemoryCaptureSettingsRecord, (tenant.id, run.principal_id)).enabled = False
    assert settings['enabled'] is True
    with database() as db:
        assert consolidation.request_consolidation(db, principal, tenant.id) == {'status': 'queued'}
    with database() as db, pytest.raises(Conflict, match='too_soon'):
        consolidation.request_consolidation(db, principal, tenant.id)
    merger = _merger({'merged': '', 'keep': 0})
    assert consolidation.consolidation_tick(database, merger, worker_id='w1') is True
    assert merger.calls  # the requested pass looked even though capture is off
    with database() as db:
        assert db.get(MemoryConsolidationStateRecord, (tenant.id, run.principal_id)).requested_at is None
        assert db.scalar(select(MemoryDraftRecord).where(MemoryDraftRecord.origin == 'background')) is None


def test_small_stores_and_failing_models_never_hold_the_lease(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    _publish_db(database, run, '只有一条', title='一条')
    _enable(database, principal, tenant.id)
    merger = _merger(lambda entries: (_ for _ in ()).throw(RuntimeError('provider down')))
    assert consolidation.consolidation_tick(database, merger, worker_id='w1') is True
    assert merger.calls == []
    with database() as db:
        assert db.get(MemoryConsolidationStateRecord, (tenant.id, run.principal_id)).lease_until is None


def test_retention_deletes_old_rejected_drafts_and_finished_jobs_only(database):  # noqa: F811
    principal, tenant, session, run, _ = stack(database)
    with database() as db, db.begin():
        repo = SqlMemoryRepository(db)
        old = service.propose(repo, tenant.id, run.principal_id, run.id, 'memory', 'old rejected text')
        service.review(repo, run.principal_id, tenant.id, UUID(old['id']), approve=False, title='')
        kept = service.propose(repo, tenant.id, run.principal_id, run.id, 'memory', 'pending text stays')
        db.get(MemoryDraftRecord, UUID(old['id'])).created_at = utc_now() - timedelta(days=31)
        db.get(MemoryDraftRecord, UUID(kept['id'])).created_at = utc_now() - timedelta(days=90)
        for state, days in (('completed', 15), ('failed', 20), ('completed', 3), ('pending', 40)):
            db.add(MemoryCaptureJobRecord(id=uuid4(), tenant_id=tenant.id, owner_user_id=run.principal_id,
                                          session_id=session.id, source_run_id=run.id, from_sequence=1, through_sequence=1,
                                          state=state, available_at=utc_now(), attempt_count=0, stored_count=0,
                                          created_at=utc_now() - timedelta(days=days),
                                          completed_at=utc_now() - timedelta(days=days) if state != 'pending' else None))
    with database() as db, db.begin():
        assert run_retention(db) == {'rejected_drafts': 1, 'capture_jobs': 2}
    with database() as db:
        assert db.get(MemoryDraftRecord, UUID(kept['id'])) is not None
        assert db.scalar(select(MemoryDraftRecord).where(MemoryDraftRecord.id == UUID(old['id']))) is None
        assert sorted(job.state for job in db.scalars(select(MemoryCaptureJobRecord))) == ['completed', 'pending']
        assert repo_tombstoned(db, tenant.id, run.principal_id, 'old rejected text')


def repo_tombstoned(db, tenant_id, owner_id, text):
    from nexus_memory import text as memtext
    return SqlMemoryRepository(db).is_tombstoned(tenant_id, owner_id, memtext.fingerprint(text))


def test_migration_adds_and_removes_the_consolidation_state(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    url = f'sqlite:///{tmp_path / "m3.db"}'
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'e8f4c6b1d3a5')
    assert 'memory_consolidation_state' in inspect(create_engine(url)).get_table_names()
    command.downgrade(config, 'd7e3b5a9c2f4')
    assert 'memory_consolidation_state' not in inspect(create_engine(url)).get_table_names()
