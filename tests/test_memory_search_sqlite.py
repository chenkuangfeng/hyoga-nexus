"""Memory keyword search on a real database: SQLite FTS5 and the portable LIKE path must agree.

Covers publication-time index maintenance, supersession, archive/disable/expiry filtering at query time,
owner isolation, literal query operators, timezone-safe validity, and the model's search_memory tool.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text as sql

from nexus_core.platform import utc_now
from nexus_core.runtime import ModelChunk
from nexus_memory import service
from nexus_memory.ports import UNSET
from nexus_platform.memory.repository import SqlMemoryRepository
from nexus_platform.persistence.models import UserRecord
from nexus_worker.__main__ import run_once

from test_native_runtime import FakeModel, call, stack
from test_platform import database  # noqa: F401 (pytest fixture)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def publish(db, run, owner, tenant_id, content, title, *, entry_id=None, base_version=None, expected=0):
    repo = SqlMemoryRepository(db)
    outcome = service.propose(repo, tenant_id, owner, run.id, 'memory', content,
                              entry_id=entry_id, base_version=base_version)
    assert outcome['status'] == 'pending', outcome
    result = service.review(repo, owner, tenant_id, UUID(outcome['id']), approve=True, title=title,
                            entry_id=entry_id, expected_version=expected)
    return UUID(result['id'])


def hits(db, tenant_id, owner, query, now=NOW):
    return sorted(h['title'] for h in service.search(SqlMemoryRepository(db), tenant_id, owner, query, now=now))


def test_fts_index_exists_and_two_character_chinese_words_match(database):
    principal, tenant, _, run, _ = stack(database, [])
    with database() as db:
        with db.begin():
            publish(db, run, run.principal_id, tenant.id, '用户喜欢用中文回复，并偏好简洁的代码风格', 'Style')
    with database() as db:
        assert SqlMemoryRepository(db)._fts_available() is True
        assert hits(db, tenant.id, run.principal_id, '偏好') == ['Style']
        assert hits(db, tenant.id, run.principal_id, '喜欢') == ['Style']
        assert hits(db, tenant.id, run.principal_id, '中文回复') == ['Style']
        assert hits(db, tenant.id, run.principal_id, '偏好 代码') == ['Style']
        assert hits(db, tenant.id, run.principal_id, '偏好 数据库') == []


def test_single_character_queries_fall_back_to_content_substring(database):
    _, tenant, _, run, _ = stack(database, [])
    with database() as db:
        with db.begin():
            publish(db, run, run.principal_id, tenant.id, '部署使用 PostgreSQL', 'Deploy')
    with database() as db:
        assert hits(db, tenant.id, run.principal_id, '署') == ['Deploy']
        assert hits(db, tenant.id, run.principal_id, '署 postgresql') == ['Deploy']


def test_fts_and_like_paths_return_the_same_hits(database, monkeypatch):
    _, tenant, _, run, _ = stack(database, [])
    corpus = [
        ('用户偏好简洁的回复风格', 'A'),
        ('生产环境使用 PostgreSQL 与 Alembic 迁移', 'B'),
        ('Use checklist before release; checklist v2', 'C'),
        ('中文回复需要引用来源', 'D'),
    ]
    with database() as db:
        with db.begin():
            for content, title in corpus:
                publish(db, run, run.principal_id, tenant.id, content, title)
    queries = ['偏好', '中文回复', '回复 风格', 'PostgreSQL', 'checklist', 'release', '来源', '回', '不存在的词']
    with database() as db:
        with_fts = {q: hits(db, tenant.id, run.principal_id, q) for q in queries}
    with database() as db:
        monkeypatch.setattr(SqlMemoryRepository, '_fts_available', lambda self: False)
        without_fts = {q: hits(db, tenant.id, run.principal_id, q) for q in queries}
    assert with_fts == without_fts
    assert with_fts['偏好'] == ['A'] and with_fts['不存在的词'] == []


def test_query_operators_and_quotes_are_literal(database):
    _, tenant, _, run, _ = stack(database, [])
    with database() as db:
        with db.begin():
            publish(db, run, run.principal_id, tenant.id, 'alpha beta', 'AB')
            publish(db, run, run.principal_id, tenant.id, 'gamma delta', 'GD')
    with database() as db:
        assert hits(db, tenant.id, run.principal_id, 'alpha OR gamma') == []
        # Operators are words: NEAR is searched as a literal term, so it matches nothing here.
        assert hits(db, tenant.id, run.principal_id, '"alpha" NEAR(beta)') == []
        assert hits(db, tenant.id, run.principal_id, '"alpha" beta') == ['AB']
        # Punctuation is dropped by the tokenizer, so no wildcard is ever applied.
        assert hits(db, tenant.id, run.principal_id, 'alpha*') == ['AB']


def test_superseded_version_is_no_longer_found(database):
    _, tenant, _, run, _ = stack(database, [])
    with database() as db:
        with db.begin():
            entry = publish(db, run, run.principal_id, tenant.id, 'old wording zebra', 'Note')
    with database() as db:
        with db.begin():
            publish(db, run, run.principal_id, tenant.id, 'new wording giraffe', 'Note', entry_id=entry,
                    base_version=1, expected=1)
    with database() as db:
        assert hits(db, tenant.id, run.principal_id, 'zebra') == []
        assert hits(db, tenant.id, run.principal_id, 'giraffe') == ['Note']
        remaining = db.execute(sql('SELECT count(*) FROM memory_fts')).scalar()
        assert remaining == 1  # only the current version stays in the keyword index


def test_disabled_archived_and_expired_entries_are_filtered_at_query_time(database):
    _, tenant, _, run, _ = stack(database, [])
    owner = run.principal_id
    with database() as db:
        with db.begin():
            off = publish(db, run, owner, tenant.id, 'kiwi disabled note', 'Off')
            gone = publish(db, run, owner, tenant.id, 'kiwi archived note', 'Gone')
            old = publish(db, run, owner, tenant.id, 'kiwi expired note', 'Old')
            publish(db, run, owner, tenant.id, 'kiwi live note', 'Live')
            service.set_availability(SqlMemoryRepository(db), owner, tenant.id, off, enabled=False)
            service.archive(SqlMemoryRepository(db), owner, tenant.id, gone)
            service.set_availability(SqlMemoryRepository(db), owner, tenant.id, old,
                                     valid_until=NOW - timedelta(hours=1))
    with database() as db:
        assert hits(db, tenant.id, owner, 'kiwi') == ['Live']
    with database() as db:
        with db.begin():
            service.set_availability(SqlMemoryRepository(db), owner, tenant.id, off, enabled=True)
    with database() as db:
        assert hits(db, tenant.id, owner, 'kiwi') == ['Live', 'Off']


def test_validity_is_compared_in_utc_regardless_of_the_offset_given(database):
    _, tenant, _, run, _ = stack(database, [])
    owner = run.principal_id
    with database() as db:
        with db.begin():
            later = publish(db, run, owner, tenant.id, 'mango later', 'Later')
            # 2026-11-01 09:00 at UTC+08:00 is 01:00 UTC: already past at NOW (12:00 UTC).
            service.set_availability(SqlMemoryRepository(db), owner, tenant.id, later,
                                     valid_until=datetime(2026, 11, 1, 9, 0, tzinfo=timezone(timedelta(hours=8))))
    with database() as db:
        assert hits(db, tenant.id, owner, 'mango') == []
    with database() as db:
        assert hits(db, tenant.id, owner, 'mango', now=datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc)) == ['Later']


def test_owner_isolation_holds_in_the_sql_filter(database):
    _, tenant, _, run, _ = stack(database, [])
    other = uuid4()
    fingerprint = '0' * 64
    with database() as db:
        with db.begin():
            db.add(UserRecord(id=other, display_name='other', status='active', is_platform_admin=False,
                              created_at=utc_now()))
            repo = SqlMemoryRepository(db)
            draft_id = repo.create_draft(tenant_id=tenant.id, source_run_id=run.id, kind='memory',
                                         diff='papaya foreign', fingerprint=fingerprint, base_version=None,
                                         origin='foreground', source_message_ids=())
            entry = repo.create_entry(tenant_id=tenant.id, owner_id=other, kind='memory', title='Foreign', project='')
            repo.append_version(entry_id=entry.id, version=1, content='papaya foreign', source_run_id=run.id,
                                source_draft_id=draft_id, reviewer_id=other, fingerprint=fingerprint,
                                source_message_ids=())
    with database() as db:
        with db.begin():
            publish(db, run, run.principal_id, tenant.id, 'papaya mine', 'Mine')
    with database() as db:
        assert hits(db, tenant.id, other, 'papaya') == ['Foreign']
        assert hits(db, tenant.id, run.principal_id, 'papaya') == ['Mine']


def test_model_can_search_memory_and_receives_pointers_not_bodies(database):
    principal, tenant, _, run, _ = stack(database, ['search_memory'])
    with database() as db:
        with db.begin():
            entry = publish(db, run, run.principal_id, tenant.id, '偏好简洁的代码风格', 'Style')
    model = FakeModel([[call('search_memory', '{"query":"偏好"}')], [ModelChunk('text', text='done')]])
    run_once(database, 'worker', model_factory=lambda _: model)
    tool_messages = [m.content for m in model.requests[1].messages if m.role == 'tool']
    assert tool_messages and str(entry) in tool_messages[0] and 'Style' in tool_messages[0]
    assert '偏好简洁的代码风格' in tool_messages[0]  # snippet only, and the body is short enough to be the snippet


def test_failed_index_write_rolls_back_the_whole_publication(database, monkeypatch):
    from nexus_platform.persistence.models import MemoryEntryRecord, MemoryVersionRecord

    _, tenant, _, run, _ = stack(database, [])
    original = SqlMemoryRepository.append_version

    def fail_after_index(self, **kwargs):
        original(self, **kwargs)
        raise RuntimeError('index write failed')

    monkeypatch.setattr(SqlMemoryRepository, 'append_version', fail_after_index)
    with database() as db:
        with pytest.raises(RuntimeError, match='index write failed'):
            with db.begin():
                publish(db, run, run.principal_id, tenant.id, 'durian rollback probe', 'Probe')
    monkeypatch.setattr(SqlMemoryRepository, 'append_version', original)
    with database() as db:
        assert db.query(MemoryEntryRecord).count() == 0
        assert db.query(MemoryVersionRecord).count() == 0
        assert db.execute(sql('SELECT count(*) FROM memory_fts')).scalar() == 0
        assert hits(db, tenant.id, run.principal_id, 'durian') == []
