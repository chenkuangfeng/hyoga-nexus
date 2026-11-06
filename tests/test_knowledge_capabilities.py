"""Knowledge capability catalog (openspec 2026-11-06-knowledge-base K0)."""
import pytest

from nexus_core.platform import Principal
from nexus_knowledge import capabilities as caps

from test_model_settings import settings_client  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)


@pytest.fixture
def clean_catalog():
    saved = dict(caps._AVAILABLE)
    caps.reset_for_tests()
    yield
    caps._AVAILABLE.clear()
    caps._AVAILABLE.update(saved)


def test_catalog_keeps_the_whole_weknora_feature_set():
    keys = {(item.group, item.key) for item in caps.CATALOG}
    assert {('kb_type', 'document'), ('kb_type', 'faq'), ('kb_type', 'wiki')} <= keys
    assert {('graph_mode', 'entity'), ('graph_mode', 'graphrag_light'), ('graph_mode', 'graphrag_general')} <= keys
    assert {('graph_store', 'builtin'), ('graph_store', 'neo4j')} <= keys
    first_batch = {'sqlite', 'postgres', 'qdrant', 'elasticsearch', 'milvus'}
    engines = {item.key: item.stage for item in caps.CATALOG if item.group == 'vector_engine'}
    assert all(engines[name] == 'K1' for name in first_batch)
    assert {'opensearch', 'weaviate', 'doris', 'tencent_vectordb', 'infinity'} <= set(engines)
    assert len([item for item in caps.CATALOG if item.group == 'datasource']) == 18
    assert all(item.group in caps.GROUPS for item in caps.CATALOG)


def test_items_are_planned_until_code_marks_them(clean_catalog):
    rows = {(row['group'], row['key']): row for row in caps.snapshot()}
    assert rows[('vector_engine', 'qdrant')]['status'] == 'planned'
    with pytest.raises(caps.CapabilityPlanned) as error:
        caps.require_available('kb_type', 'faq')
    assert error.value.item.stage == 'K3'

    caps.mark_available('vector_engine', 'qdrant', verified=False)
    caps.mark_available('vector_engine', 'sqlite')
    rows = {(row['group'], row['key']): row for row in caps.snapshot()}
    assert (rows[('vector_engine', 'qdrant')]['status'], rows[('vector_engine', 'qdrant')]['verified']) == (
        'available', False)
    assert rows[('vector_engine', 'sqlite')]['verified'] is True
    caps.require_available('vector_engine', 'sqlite')


def test_unknown_keys_are_rejected(clean_catalog):
    with pytest.raises(KeyError):
        caps.mark_available('vector_engine', 'nope')
    with pytest.raises(ValueError):
        caps.require_available('kb_type', 'nope')


def test_capability_endpoint_is_for_members_only(settings_client, clean_catalog):
    client, model_path, identity, owner, member, tenant_id = settings_client
    path = f'/api/v1/tenants/{tenant_id}/knowledge/capabilities'
    identity[0] = member
    response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['groups'] == list(caps.GROUPS)
    assert {'group', 'key', 'label', 'stage', 'status', 'verified'} == set(body['items'][0])
    identity[0] = Principal('stranger', 'test')
    assert client.get(path).status_code == 404
