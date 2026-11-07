"""Knowledge HTTP API on SQLite (openspec 2026-11-06-knowledge-base K1 API)."""
import asyncio

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, utc_now
from nexus_platform.identity.service import resolve_user
from nexus_platform.knowledge import jobs
from nexus_platform.persistence.models import MembershipRecord, VectorStoreRecord
from nexus_platform.tenants.service import create_tenant

from test_platform import database  # noqa: F401 (pytest fixture)

OWNER = Principal('api-kb-owner', 'test')
MEMBER = Principal('api-kb-member', 'test')
STRANGER = Principal('api-kb-stranger', 'test')


@pytest.fixture
def api(database, deployment_config, tmp_path):
    deployment_config(f'[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n'
                      f'[knowledge]\ndata_dir = "{tmp_path / "k"}"\nmax_upload_mb = 1\n')
    with database() as db:
        tenant = create_tenant(db, OWNER, 'KB API')
        create_tenant(db, STRANGER, 'Other')
        with db.begin():
            member = resolve_user(db, MEMBER)
            db.add(MembershipRecord(tenant_id=tenant.id, user_id=member.id, role='contributor', status='active',
                                    joined_at=utc_now()))
    identity = [OWNER]

    def session():
        with database() as db:
            yield db
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: identity[0]
    with TestClient(app) as client:
        yield client, f'/api/v1/tenants/{tenant.id}/knowledge', identity, database
    app.dependency_overrides.clear()


def drain(factory):
    while asyncio.run(jobs.run_due(factory, 5)):
        pass


def test_base_document_and_search_flow(api):
    client, path, identity, factory = api
    created = client.post(path + '/bases', json={'name': '产品手册', 'indexing_strategy': {'vector': False, 'keyword': True}})
    assert created.status_code == 201, created.text
    kb = created.json()
    assert kb['vector_engine'] == 'sqlite' and kb['vector_store_id'] == 'builtin' and kb['can_edit'] is True
    kb_id = kb['id']
    upload = client.post(f'{path}/bases/{kb_id}/documents',
                         files={'file': ('手册.md', '# 安装\n先运行安装程序。'.encode(), 'text/markdown')})
    assert upload.status_code == 201, upload.text
    doc = upload.json()['document']
    assert doc['parse_status'] == 'pending' and upload.json()['deduplicated'] is False
    again = client.post(f'{path}/bases/{kb_id}/documents', files={'file': ('copy.md', '# 安装\n先运行安装程序。'.encode())})
    assert again.json()['deduplicated'] is True
    drain(factory)
    listed = client.get(f'{path}/bases/{kb_id}/documents').json()
    assert listed['total'] == 1 and listed['items'][0]['parse_status'] == 'completed'
    chunks = client.get(f'{path}/documents/{doc["id"]}/chunks').json()
    assert chunks['total'] == 1 and chunks['items'][0]['section'] == ['安装']
    identity[0] = MEMBER
    found = client.post(path + '/search', json={'query': '安装程序'})
    assert found.status_code == 200, found.text
    assert found.json()['items'][0]['filename'] == '手册.md'
    download = client.get(f'{path}/documents/{doc["id"]}/download')
    assert download.status_code == 200 and '安装程序' in download.content.decode()
    # The member did not create the base: changes are refused.
    assert client.delete(f'{path}/documents/{doc["id"]}').status_code == 403
    identity[0] = OWNER
    activity = client.get(f'{path}/bases/{kb_id}/activity').json()['items']
    assert {'knowledge_base.created', 'knowledge_document.uploaded'} <= {item['action'] for item in activity}
    assert client.delete(f'{path}/bases/{kb_id}').status_code == 204
    assert client.get(f'{path}/bases/{kb_id}').status_code == 404


def test_planned_features_and_limits_are_refused(api):
    client, path, identity, _ = api
    wiki = client.post(path + '/bases', json={'name': 'wiki', 'type': 'wiki'})
    assert wiki.status_code == 422 and wiki.json()['error']['code'] == 'capability_planned'
    assert wiki.json()['error']['details']['stage'] == 'K6'
    kb_id = client.post(path + '/bases', json={'name': 'x', 'indexing_strategy': {'vector': False}}).json()['id']
    too_big = client.post(f'{path}/bases/{kb_id}/documents', files={'file': ('a.txt', b'x' * (1024 * 1024 + 1))})
    assert too_big.status_code == 422
    unsupported = client.post(f'{path}/bases/{kb_id}/documents', files={'file': ('a.exe', b'x')})
    assert unsupported.status_code == 422
    store = client.post(path + '/vector-stores', json={'name': 'w', 'engine': 'weaviate'})
    assert store.json()['error']['code'] == 'capability_planned'
    identity[0] = STRANGER
    assert client.get(path + '/bases').status_code == 404


def test_vector_store_registry_hides_secrets(api):
    client, path, identity, factory = api
    listed = client.get(path + '/vector-stores').json()['items']
    assert listed[0]['id'] == 'builtin' and listed[0]['engine'] == 'sqlite'
    created = client.post(path + '/vector-stores', json={
        'name': 'Qdrant 测试', 'engine': 'qdrant',
        'connection_config': {'url': 'http://127.0.0.1:1', 'api_key': 'secret-key'}})
    assert created.status_code == 201, created.text
    assert created.json()['connection_config']['api_key'] == '******'
    store_id = created.json()['id']
    with factory() as db:
        stored = db.get(VectorStoreRecord, __import__('uuid').UUID(store_id)).connection_config['api_key']
        assert stored.startswith('enc:') and 'secret-key' not in stored
    updated = client.put(f'{path}/vector-stores/{store_id}', json={
        'name': 'Qdrant', 'connection_config': {'url': 'http://127.0.0.1:1', 'api_key': '******'}})
    assert updated.status_code == 200
    with factory() as db:
        assert db.get(VectorStoreRecord, __import__('uuid').UUID(store_id)).connection_config['api_key'] == stored
    test = client.post(f'{path}/vector-stores/{store_id}/test').json()
    assert test['ok'] is False and test['code'] == 'connection_failed'
    assert client.post(f'{path}/vector-stores/builtin/test').json()['ok'] is True
    identity[0] = MEMBER
    assert client.post(path + '/vector-stores', json={'name': 'm', 'engine': 'sqlite',
                                                      'connection_config': {'path': 'x.db'}}).status_code == 403
    identity[0] = OWNER
    kb = client.post(path + '/bases', json={'name': 'q', 'vector_store_id': store_id,
                                            'indexing_strategy': {'vector': False, 'keyword': True}})
    assert kb.status_code == 422  # Qdrant needs vectors
    assert client.delete(f'{path}/vector-stores/{store_id}').status_code == 204


def test_capabilities_reflect_implemented_features(api):
    client, path, _, _ = api
    items = {(i['group'], i['key']): i for i in client.get(path + '/capabilities').json()['items']}
    assert items[('kb_type', 'document')]['status'] == 'available'
    assert items[('vector_engine', 'milvus')]['verified'] is False
    assert items[('kb_type', 'wiki')]['status'] == 'planned'
    assert items[('kb_feature', 'retrieval_test')]['status'] == 'available'


def test_vector_store_types_list_every_engine(api):
    client, path, _, _ = api
    items = {item['type']: item for item in client.get(path + '/vector-store-types').json()['items']}
    assert {'sqlite', 'postgres', 'qdrant', 'elasticsearch', 'milvus', 'weaviate'} <= set(items)
    assert items['milvus']['status'] == 'available' and items['milvus']['verified'] is False
    assert any(field['name'] == 'token' and field['sensitive'] for field in items['milvus']['connection_fields'])
    assert items['weaviate']['status'] == 'planned' and items['weaviate']['connection_fields'] == []


def test_chunk_preview_parser_engines_and_engine_rules(api):
    client, path, _, _ = api
    preview = client.post(path + '/chunk-preview', json={
        'text': '# 甲\n' + '正文。' * 80 + '\n# 乙\n' + '正文。' * 80,
        'chunking_config': {'chunk_size': 200, 'chunk_overlap': 20, 'strategy': 'auto'}})
    assert preview.status_code == 200, preview.text
    data = preview.json()['data']
    assert data['selected_tier'] == 'heading' and data['stats']['count'] >= 4
    bad = client.post(path + '/chunk-preview', json={'text': 'x', 'chunking_config': {'chunk_size': 50}})
    assert bad.status_code == 422
    engines = {e['Name']: e for e in client.get(path + '/parser-engines').json()['data']}
    assert engines['builtin']['Available'] and 'docx' in engines['builtin']['FileTypes']
    assert not engines['mineru']['Available'] and engines['mineru']['UnavailableReason'].startswith('未配置')  # implemented, not set up
    assert engines['anydoc']['Available'] and 'doc' in engines['anydoc']['FileTypes']  # in-process, nothing to set up
    assert not engines['markitdown']['Available'] and engines['markitdown']['UnavailableReason'].startswith('待实现')
    rule = client.post(path + '/bases', json={'name': 'r', 'indexing_strategy': {'vector': False, 'keyword': True},
                                              'settings': {'chunking_config': {'parser_engine_rules': [
                                                  {'file_types': ['pdf'], 'engine': 'markitdown'}]}}})
    assert rule.status_code == 422 and rule.json()['error']['code'] == 'capability_planned'
