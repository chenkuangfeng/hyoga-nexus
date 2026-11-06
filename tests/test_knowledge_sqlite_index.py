"""SQLite vector engine and local blob store (openspec 2026-11-06-knowledge-base K1.2)."""
import asyncio

import pytest

from nexus_knowledge import capabilities
from nexus_knowledge.index import IndexRow, Scope, VectorStoreError, collection_name, open_index
from nexus_knowledge.providers import BlobStoreError, open_blob_store
from nexus_knowledge.text import query_tokens, tokenize


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def index(tmp_path):
    return open_index('sqlite', {'path': str(tmp_path / 'vectors.db')})


def _rows():
    return [
        IndexRow('c1', 'kb', 'v1', tokenize('苹果 价格 上涨'), [1.0, 0.0, 0.0]),
        IndexRow('c2', 'kb', 'v1', tokenize('香蕉 价格 下跌'), [0.0, 1.0, 0.0]),
        IndexRow('c3', 'kb', 'v2', tokenize('苹果 产量'), [0.9, 0.1, 0.0]),
        IndexRow('c4', 'kb', 'v3', tokenize('苹果 秘密 文件'), [1.0, 0.0, 0.0]),
    ]


def test_engine_is_registered_and_verified():
    assert capabilities.is_available('vector_engine', 'sqlite')
    row = next(r for r in capabilities.snapshot() if r['group'] == 'vector_engine' and r['key'] == 'sqlite')
    assert row['verified'] is True
    assert collection_name('0A-b') == 'kb_0ab'


def test_vector_and_keyword_search_stay_inside_the_scope(index):
    col = collection_name('kb-1')
    run(index.upsert(col, _rows(), dimension=3))
    scope = Scope('kb', ('v1', 'v2'))
    vector = run(index.search_vector(col, [1.0, 0.0, 0.0], scope, 10))
    assert [c.chunk_id for c in vector][:2] == ['c1', 'c3']
    assert 'c4' not in {c.chunk_id for c in vector}  # v3 is out of scope although it matches best
    keyword = run(index.search_keyword(col, query_tokens('苹果'), scope, 10))
    assert {c.chunk_id for c in keyword} == {'c1', 'c3'}
    assert all(c.score > 0 for c in keyword)
    assert run(index.search_vector(col, [1.0, 0.0, 0.0], Scope('kb', ()), 10)) == []
    assert run(index.search_keyword(col, ['苹果'], Scope('kb', ()), 10)) == []


def test_upsert_replaces_by_chunk_id_and_versions_can_be_deleted(index):
    col = collection_name('kb-2')
    run(index.upsert(col, _rows(), dimension=3))
    run(index.upsert(col, [IndexRow('c1', 'kb', 'v1', tokenize('梨子'), [0.0, 0.0, 1.0])], dimension=3))
    scope = Scope('kb', ('v1', 'v2', 'v3'))
    assert {c.chunk_id for c in run(index.search_keyword(col, ['苹果'], scope, 10))} == {'c3', 'c4'}
    run(index.delete_versions(col, ['v2']))
    assert {c.chunk_id for c in run(index.search_keyword(col, ['苹果'], scope, 10))} == {'c4'}
    run(index.drop_collection(col))
    assert run(index.search_vector(col, [1.0, 0.0, 0.0], scope, 10)) == []


def test_keyword_only_rows_and_dimension_checks(index):
    col = collection_name('kb-3')
    run(index.upsert(col, [IndexRow('k1', 'kb', 'v1', tokenize('只有关键词'), None)], dimension=None))
    scope = Scope('kb', ('v1',))
    assert [c.chunk_id for c in run(index.search_keyword(col, query_tokens('关键词'), scope, 5))] == ['k1']
    assert run(index.search_vector(col, [1.0, 0.0], scope, 5)) == []
    with pytest.raises(VectorStoreError):
        run(index.upsert(col, [IndexRow('k2', 'kb', 'v1', '', [1.0])], dimension=3))
    with pytest.raises(VectorStoreError):
        run(index.search_vector(col, [0.0, 0.0], scope, 5))


def test_ping_and_invalid_configuration(tmp_path, index):
    assert run(index.ping())['engine'] == 'sqlite'
    with pytest.raises(VectorStoreError):
        open_index('sqlite', {'path': ':memory:'})
    with pytest.raises(capabilities.CapabilityPlanned):
        open_index('weaviate', {})


def test_local_blob_store_round_trip_and_key_safety(tmp_path):
    store = open_blob_store('local', {'root': str(tmp_path / 'blobs')})
    run(store.put('t/kb/doc/1', b'hello'))
    assert run(store.get('t/kb/doc/1')) == b'hello'
    run(store.delete('t/kb/doc/1'))
    run(store.delete('t/kb/doc/1'))
    with pytest.raises(BlobStoreError):
        run(store.get('t/kb/doc/1'))
    for key in ('../escape', '/abs', ''):
        with pytest.raises(BlobStoreError):
            run(store.put(key, b'x'))
    assert run(store.ping())['provider'] == 'local'
    with pytest.raises(capabilities.CapabilityPlanned):
        open_blob_store('s3', {})
