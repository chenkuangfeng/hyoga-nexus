"""Knowledge tables migration round trip (openspec 2026-11-06-knowledge-base K1.3)."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

TABLES = {'knowledge_bases', 'knowledge_documents', 'knowledge_document_versions', 'knowledge_chunks',
          'knowledge_jobs', 'vector_stores', 'storage_backends'}


def test_knowledge_tables_round_trip_on_sqlite(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'knowledge.db')
    config = Config('alembic.ini')
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = create_engine(url)
    assert TABLES <= set(inspect(engine).get_table_names())
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
