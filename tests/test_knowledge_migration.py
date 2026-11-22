"""Knowledge tables migration round trip (openspec 2026-11-06-knowledge-base K1.3)."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

TABLES = {'knowledge_bases', 'knowledge_documents', 'knowledge_document_versions', 'knowledge_chunks',
          'knowledge_jobs', 'knowledge_folders', 'vector_stores', 'storage_backends'}


def test_knowledge_tables_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'knowledge.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url)
    assert TABLES <= set(inspect(engine).get_table_names())
    unique_names = next(index for index in inspect(engine).get_indexes('knowledge_documents')
                        if index['name'] == 'uq_knowledge_documents_name')
    assert unique_names['column_names'] == ['kb_id', 'folder_path', 'filename']
    command.downgrade(config, 'b7c6d5e4f3a2')
    assert not TABLES & set(inspect(engine).get_table_names())
    assert 'memory_fts' in set(inspect(engine).get_table_names())
    command.upgrade(config, 'head')


def test_graph_tables_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'graph.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url)
    graph = {'graph_stores', 'knowledge_graph_builds', 'knowledge_graph_entities', 'knowledge_graph_relations',
             'knowledge_graph_communities', 'knowledge_graph_extractions'}
    assert graph <= set(inspect(engine).get_table_names())
    command.downgrade(config, 'c8d9e0f1a2b3')
    assert not graph & set(inspect(engine).get_table_names())
    assert 'knowledge_bases' in set(inspect(engine).get_table_names())
    command.upgrade(config, 'head')


def test_faq_table_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'faq.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url)
    assert 'knowledge_faq_entries' in set(inspect(engine).get_table_names())
    command.downgrade(config, 'd1e2f3a4b5c6')
    assert 'knowledge_faq_entries' not in set(inspect(engine).get_table_names())
    command.upgrade(config, 'head')


def test_chunk_parent_columns_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'chunks.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url)
    assert {'parent_id', 'indexed'} <= {c['name'] for c in inspect(engine).get_columns('knowledge_chunks')}
    command.downgrade(config, 'e2f3a4b5c6d7')
    assert 'parent_id' not in {c['name'] for c in inspect(engine).get_columns('knowledge_chunks')}
    command.upgrade(config, 'head')


def test_organization_columns_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'org.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url)
    columns = {c['name'] for c in inspect(engine).get_columns('knowledge_documents')}
    assert {'tag_ids', 'folder_path', 'custom_metadata'} <= columns and 'knowledge_tags' in inspect(engine).get_table_names()
    command.downgrade(config, 'f3a4b5c6d7e8')
    assert 'knowledge_tags' not in inspect(engine).get_table_names()
    assert 'folder_path' not in {c['name'] for c in inspect(engine).get_columns('knowledge_documents')}
    command.upgrade(config, 'head')


def test_enrichment_columns_and_job_kind_round_trip_on_sqlite(tmp_path):
    from sqlalchemy import text
    url = 'sqlite:///' + str(tmp_path / 'enrich.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url)
    assert 'summary' in {c['name'] for c in inspect(engine).get_columns('knowledge_document_versions')}
    assert 'questions' in {c['name'] for c in inspect(engine).get_columns('knowledge_chunks')}
    with engine.connect() as connection:
        sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE name='knowledge_jobs'")).scalar()
    assert "'enrich'" in sql
    command.downgrade(config, 'a4b5c6d7e8f9')
    with engine.connect() as connection:
        sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE name='knowledge_jobs'")).scalar()
    assert "'enrich'" not in sql
    command.upgrade(config, 'head')


def test_folder_migration_preserves_existing_document_paths(tmp_path):
    from sqlalchemy.orm import Session

    from nexus_core.platform import Principal, new_id, utc_now
    from nexus_platform.identity.service import resolve_user
    from nexus_platform.persistence.models import KnowledgeBaseRecord, KnowledgeDocumentRecord
    from nexus_platform.tenants.service import create_tenant

    config = Config('alembic.ini')
    url = 'sqlite:///' + str(tmp_path / 'existing-folders.db')
    config.attributes['database_url'] = url
    command.upgrade(config, 'a03b51d982ef')
    engine = create_engine(url)
    principal = Principal('migration-owner', 'test')
    kb_id, doc_id, now = new_id(), new_id(), utc_now()
    with Session(engine, expire_on_commit=False) as db:
        tenant_id = create_tenant(db, principal, 'Existing folder data').id
        with db.begin():
            user_id = resolve_user(db, principal).id
            db.add(KnowledgeBaseRecord(id=kb_id, tenant_id=tenant_id, name='Existing KB', created_by=user_id,
                                       created_at=now, updated_at=now))
            db.flush()
            db.add(KnowledgeDocumentRecord(id=doc_id, tenant_id=tenant_id, kb_id=kb_id, filename='existing.txt',
                                           folder_path='资料/既有目录', created_by=user_id, created_at=now, updated_at=now))
    command.upgrade(config, 'head')
    with Session(engine) as db:
        assert db.get(KnowledgeDocumentRecord, doc_id).folder_path == '资料/既有目录'
    command.downgrade(config, 'a03b51d982ef')
    with Session(engine) as db:
        assert db.get(KnowledgeDocumentRecord, doc_id).folder_path == '资料/既有目录'
