"""Memory stage 1 migration: existing published versions are backfilled and searchable on SQLite."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def _config(url, monkeypatch):
    monkeypatch.setenv('NEXUS_DATABASE_URL', url)
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    return config


def test_upgrade_backfills_existing_versions_into_the_keyword_index(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'memory-stage1.db')
    config = _config(url, monkeypatch)
    command.upgrade(config, 'a6c3e9f2b1d8')
    engine = create_engine(url)
    entry, draft, run = 'a' * 32, 'b' * 32, 'c' * 32
    with engine.begin() as db:
        db.execute(text("INSERT INTO memory_entries (id, tenant_id, owner_user_id, kind, title, project, active,"
                        " current_version, created_at) VALUES (:e, :t, :u, 'memory', 'Old', '', 1, 1, CURRENT_TIMESTAMP)"),
                   {'e': entry, 't': 'd' * 32, 'u': 'f' * 32})
        db.execute(text("INSERT INTO memory_versions (entry_id, version, content, source_run_id, source_draft_id,"
                        " reviewed_by, created_at) VALUES (:e, 1, '用户偏好简洁的代码风格', :r, :d, :u, CURRENT_TIMESTAMP)"),
                   {'e': entry, 'r': run, 'd': draft, 'u': 'f' * 32})
    command.upgrade(config, 'head')
    with engine.connect() as db:
        row = db.execute(text('SELECT tokens, fingerprint, search_id FROM memory_versions WHERE entry_id = :e'),
                         {'e': entry}).one()
        assert row.tokens.split() == ['用户', '户偏', '偏好', '好简', '简洁', '洁的', '的代', '代码', '码风', '风格']
        assert len(row.fingerprint) == 64 and row.search_id == 1
        hit = db.execute(text("SELECT rowid FROM memory_fts WHERE memory_fts MATCH '\"偏好\"'")).all()
        assert [r.rowid for r in hit] == [1]
        enabled = db.execute(text('SELECT enabled FROM memory_entries WHERE id = :e'), {'e': entry}).scalar()
        assert enabled in (1, True)
    command.downgrade(config, 'a6c3e9f2b1d8')
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')


def test_fresh_database_gets_the_keyword_index_from_the_migration(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'memory-fresh.db')
    config = _config(url, monkeypatch)
    command.upgrade(config, 'head')
    engine = create_engine(url)
    with engine.connect() as db:
        assert db.execute(text("SELECT name FROM sqlite_master WHERE name = 'memory_fts'")).scalar() == 'memory_fts'
        assert db.execute(text("SELECT name FROM sqlite_master WHERE name = 'memory_tombstones'")).scalar() == 'memory_tombstones'
