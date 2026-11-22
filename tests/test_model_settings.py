"""Settings acceptance: private credentials, immutable defaults and safe destinations."""
import asyncio
import json
import socket
from uuid import UUID
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_platform import database
from nexus_api.main import app
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal, utc_now, CredentialRef, new_id
from nexus_core.runtime import RuntimeFault
from nexus_platform.tenants.service import create_tenant
from nexus_platform.identity.service import resolve_user
from nexus_platform.persistence.models import (
    MembershipRecord, ModelProfileVersionRecord, ModelProviderRecord, ProviderCredentialRecord,
    AuditRecord, RunRecord, SessionRecord, AgentVersionRecord,
)
from nexus_platform.models.provider_settings import StoredCredentialResolver, decrypt
from nexus_platform.sessions.service import create_session
from nexus_platform.runs.service import create_run
from nexus_runtimes.native.models.network import PinnedTransport, validate_url


@pytest.fixture
def settings_client(database, deployment_config):
    deployment_config(f'[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n')
    owner = Principal('settings-owner', 'test')
    member = Principal('settings-member', 'test')
    with database() as db:
        tenant = create_tenant(db, owner, 'Settings')
        with db.begin():
            user = resolve_user(db, member)
            db.add(MembershipRecord(tenant_id=tenant.id, user_id=user.id, role='contributor', status='active', joined_at=utc_now()))
    allow_personal_models(database, owner, tenant.id)
    identity = [owner]
    def session():
        with database() as db:
            yield db
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: identity[0]
    with TestClient(app) as client:
        yield client, '/api/v1/tenants/' + str(tenant.id) + '/model-settings', identity, owner, member, tenant.id
    app.dependency_overrides.clear()


def add_member_role(client, tenant_path, identity, owner):
    """Give the seeded member a role that may create agents; built-in member roles have no agent access."""
    identity[0] = owner
    members = client.get(tenant_path + '/members').json()
    member_user_id = next(item['user_id'] for item in members if item['role'] == 'contributor')
    role = client.post(tenant_path + '/roles', json={'name': 'agent-builder', 'menus': ['agents'], 'apis': ['agents:write']})
    assert role.status_code == 201, role.text
    assigned = client.put(tenant_path + '/members/' + member_user_id + '/roles/' + role.json()['id'])
    assert assigned.status_code == 204, assigned.text


def allow_personal_models(database, owner, tenant_id):
    """These tests cover personal providers, which an enterprise must allow (openspec 2026-11-11 decision 4)."""
    from nexus_platform.tenants.policies import update_policy
    with database() as db:
        update_policy(db, owner, tenant_id, {'personal_models': True})


def add_provider(client, path, scope='personal', key='test-private-key'):
    response = client.post(path + '/providers', json={'name': 'Provider', 'base_url': 'https://model.example/v1', 'scope': scope, 'api_key': key})
    assert response.status_code == 201, response.text
    return response.json()


def add_model(client, path, provider, name='test-model'):
    response = client.post(path + '/providers/' + provider['id'] + '/models', json={'name': name})
    assert response.status_code == 201, response.text
    return response.json()


def test_settings_defaults_versions_and_secret_lifecycle(settings_client, database):
    client, path, identity, owner, member, tenant_id = settings_client
    provider = add_provider(client, path)
    model = add_model(client, path, provider)
    second = add_model(client, path, provider, 'second-model')
    other = add_provider(client, path)
    assert len(client.get(path).json()['providers']) == 2
    assert client.put(path + '/default', json={'version_id': model['version_id']}).status_code == 200
    agent = client.post(path + '/agents', json={'name': 'My agent'}).json()
    with database() as db:
        session = create_session(db, owner, tenant_id, agent_version_id=UUID(agent['published_version_id']))
        run, _ = create_run(db, owner, tenant_id, session.id, message='Hi', idempotency_key='test')
    with database() as db:
        version = db.get(ModelProfileVersionRecord, UUID(model['version_id']))
        reference = CredentialRef(version.credential_reference_id, 'encrypted', 'encrypted://' + str(version.credential_reference_id), str(tenant_id))
        run_id, principal_id = run.id, run.principal_id
        db.get(RunRecord, run_id).status = 'running'
        db.commit()
        secrets = list(db.scalars(select(ProviderCredentialRecord)))
        assert all('test-private-key' not in row.encrypted_key for row in secrets)
        assert all('test-private-key' not in json.dumps(row.metadata_json) for row in db.scalars(select(AuditRecord)))
    resolver = StoredCredentialResolver(database, None)
    assert resolver.resolve(reference, principal_id=principal_id, run_id=run_id).reveal_for_call() == 'test-private-key'
    assert 'test-private-key' not in client.get(path).text
    assert client.put(path + '/default', json={'version_id': second['version_id']}).status_code == 200
    updated = client.put(path + '/providers/' + provider['id'] + '/models/' + model['id'], json={'name': 'updated-model'})
    assert updated.status_code == 200
    with database() as db:
        assert db.get(AgentVersionRecord, UUID(agent['published_version_id'])).model_profile_version_id == UUID(model['version_id'])
        assert db.get(SessionRecord, session.id).agent_version_id == UUID(agent['published_version_id'])
    rotation = client.put(path + '/providers/' + provider['id'], json={'name': 'Renamed', 'base_url': 'https://model.example/v1', 'api_key': 'rotated-key'})
    assert rotation.status_code == 200, rotation.text
    assert resolver.resolve(reference, principal_id=principal_id, run_id=run_id).reveal_for_call() == 'rotated-key'
    changed = client.put(path + '/providers/' + provider['id'], json={'name': 'Renamed', 'base_url': 'https://other.example/v1', 'api_key': 'destination-key'})
    assert changed.status_code == 200, changed.text
    assert resolver.resolve(reference, principal_id=principal_id, run_id=run_id).reveal_for_call() == 'rotated-key'
    assert client.delete(path + '/providers/' + provider['id']).status_code == 200
    assert client.get(path).json()['defaults'] == {}
    with pytest.raises(Exception, match='unavailable'):
        resolver.resolve(reference, principal_id=principal_id, run_id=run_id)


def test_personal_isolation_and_tenant_admin(settings_client):
    client, path, identity, owner, member, _ = settings_client
    private = add_provider(client, path)
    model = add_model(client, path, private)
    agent_response = client.post(path + '/agents', json={'name': 'Private', 'model_profile_version_id': model['version_id']})
    assert agent_response.status_code == 201
    agent = agent_response.json()
    assert client.put(path + '/default', json={'scope': 'tenant', 'version_id': model['version_id']}).status_code == 403
    shared = add_provider(client, path, 'tenant')
    shared_model = add_model(client, path, shared)
    assert client.put(path + '/default', json={'scope': 'tenant', 'version_id': shared_model['version_id']}).status_code == 200
    identity[0] = member
    data = client.get(path).json()
    assert [row['id'] for row in data['providers']] == [shared['id']]
    assert not data['can_manage_tenant']
    assert client.delete(path + '/providers/' + private['id']).status_code == 404
    assert client.delete(path + '/providers/' + shared['id']).status_code == 403
    assert client.post(path + '/agents', json={'name': 'Stolen', 'model_profile_version_id': model['version_id']}).status_code == 404
    tenant_path = path.removesuffix('/model-settings')
    assert all(item['id'] != agent['id'] for item in client.get(tenant_path + '/agents').json())
    assert client.get(tenant_path + '/agents/' + agent['id']).status_code == 404
    assert client.post(tenant_path + '/sessions', json={'agent_version_id': agent['published_version_id']}).status_code == 404
    personal = add_provider(client, path)
    member_model = add_model(client, path, personal)
    assert client.put(path + '/default', json={'version_id': member_model['version_id']}).status_code == 200
    add_member_role(client, tenant_path, identity, owner)
    identity[0] = member
    created = client.post(path + '/agents', json={'name': 'Member agent'})
    assert created.status_code == 201, created.text


def test_missing_key_invalid_input_and_key_not_reflected(settings_client, deployment_config):
    client, path, *_ = settings_client
    deployment_config('')
    result = client.post(path + '/providers', json={'name': 'P', 'base_url': 'https://public.example/v1', 'api_key': 'do-not-reflect'})
    assert result.status_code == 503
    assert 'do-not-reflect' not in result.text
    invalid = client.post(path + '/providers', json={'name': 'P', 'base_url': 'http://127.0.0.1/v1', 'api_key': 'do-not-reflect'})
    assert invalid.status_code == 422
    assert 'do-not-reflect' not in invalid.text


def test_test_connection_bounded_sanitized_and_rate_limited(settings_client, monkeypatch):
    client, path, *_ = settings_client
    provider = add_provider(client, path)
    model = add_model(client, path, provider)
    import nexus_api.http.model_settings as endpoint
    class Fake:
        def __init__(self, **kwargs): self.kwargs = kwargs
        async def stream(self, request):
            assert request.max_output_tokens == 32
            raise RuntimeFault('model_rate_limited')
            yield
        async def close(self): pass
    monkeypatch.setattr(endpoint, 'OpenAICompatibleModel', Fake)
    monkeypatch.setattr(endpoint, 'provider_client', lambda *a, **kw: None)
    route = path + '/providers/' + provider['id'] + '/models/' + model['id'] + '/test'
    result = client.post(route)
    assert result.json()['code'] == 'model_rate_limited'
    assert 'test-private-key' not in result.text
    assert client.post(route).status_code == 409


def test_destination_transport_pins_validated_ip_and_rejects_private(monkeypatch):
    async def check():
        loop = asyncio.get_running_loop()
        async def resolve(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        monkeypatch.setattr(loop, 'getaddrinfo', resolve)
        transport = PinnedTransport('https://model.example/v1')
        sent = []
        class Inner:
            async def handle_async_request(self, request):
                sent.append(request)
                return httpx.Response(200)
            async def aclose(self): pass
        await transport.inner.aclose()
        transport.inner = Inner()
        await transport.handle_async_request(httpx.Request('POST', 'https://model.example/v1/chat/completions'))
        assert sent[0].url.host == '8.8.8.8'
        assert sent[0].headers['Host'] == 'model.example'
        assert sent[0].extensions['sni_hostname'] == 'model.example'
        async def private(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        monkeypatch.setattr(loop, 'getaddrinfo', private)
        with pytest.raises(RuntimeFault, match='model_destination_denied'):
            await transport.handle_async_request(httpx.Request('POST', 'https://model.example/v1/chat/completions'))
        assert len(sent) == 1
        with pytest.raises(RuntimeFault):
            await transport.handle_async_request(httpx.Request('GET', 'https://other.example/'))
        await transport.aclose()
    asyncio.run(check())
    for url in ('http://public.example/v1', 'https://127.0.0.1', 'https://169.254.169.254', 'https://user:key@public.example', 'https://public.example/?key=secret'):
        with pytest.raises(RuntimeFault):
            validate_url(url)


def test_credential_integrity_and_legacy_api_cannot_bypass_scope(settings_client, database, deployment_config):
    client, path, identity, owner, member, tenant_id = settings_client
    provider = add_provider(client, path)
    model = add_model(client, path, provider)
    with database() as db:
        secret = db.scalar(select(ProviderCredentialRecord))
        credential_id = str(secret.credential_id)
        assert decrypt(secret) == 'test-private-key'
        deployment_config(f'[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n')
        from nexus_platform.errors import ServiceUnavailable
        with pytest.raises(ServiceUnavailable, match='cannot be decrypted'):
            decrypt(secret)
    tenant_path = path.removesuffix('/model-settings')
    body = {'name': 'bypass', 'provider': 'other', 'model_name': 'test', 'options': {}, 'credential_reference_id': credential_id}
    assert client.post(tenant_path + '/model-profiles', json=body).status_code == 422
    assert client.put(tenant_path + '/model-profiles/' + model['id'] + '/versions', json={
        'model_name': 'bypass', 'options': {}, 'credential_reference_id': None}).status_code == 422


def test_defaults_fallback_and_model_edit_advances_only_defaults(settings_client):
    client, path, identity, owner, member, _ = settings_client
    provider = add_provider(client, path, 'tenant')
    model = add_model(client, path, provider)
    assert client.put(path + '/default', json={'scope': 'tenant', 'version_id': model['version_id']}).status_code == 200
    updated = client.put(path + '/providers/' + provider['id'] + '/models/' + model['id'], json={'name': 'next-model'}).json()
    assert client.get(path).json()['defaults']['tenant']['chat'] == updated['version_id']
    add_member_role(client, path.removesuffix('/model-settings'), identity, owner)
    identity[0] = member
    assert client.post(path + '/agents', json={'name': 'Use space default'}).status_code == 201
    assert client.put(path + '/default', json={'version_id': updated['version_id']}).status_code == 200
    assert client.put(path + '/default', json={'version_id': None}).status_code == 200
    assert 'personal' not in client.get(path).json()['defaults']


def test_model_update_clears_reasoning_effort_only_when_requested(settings_client, database):
    client, path, *_ = settings_client
    provider = add_provider(client, path, 'tenant')
    models = f'{path}/providers/{provider["id"]}/models'
    created = client.post(models, json={'name': 'chat-model', 'options': {'reasoning_effort': 'high'}})
    assert created.status_code == 201
    original = created.json()
    model = f'{models}/{original["id"]}'
    renamed = client.put(model, json={'name': 'renamed-chat'})
    assert renamed.status_code == 200
    cleared = client.put(model, json={'name': 'renamed-chat', 'options': {'reasoning_effort': ''}})
    assert cleared.status_code == 200
    with database() as db:
        def options(result):
            return db.get(ModelProfileVersionRecord, UUID(result['version_id'])).options

        assert options(original)['reasoning_effort'] == 'high'
        assert options(renamed.json())['reasoning_effort'] == 'high'
        assert 'reasoning_effort' not in options(cleared.json())


def test_model_type_is_validated_fixed_and_limits_defaults(settings_client):
    """Typed models: unknown types are rejected, a model keeps its type, and defaults are per type."""
    client, path, *_ = settings_client
    provider = add_provider(client, path, 'tenant')
    assert client.post(path + '/providers/' + provider['id'] + '/models', json={'name': 'x', 'model_type': 'translate'}).status_code == 422
    chat = client.post(path + '/providers/' + provider['id'] + '/models', json={'name': 'chat-model'}).json()
    embed = client.post(path + '/providers/' + provider['id'] + '/models', json={'name': 'embed-model', 'model_type': 'embedding'})
    assert embed.status_code == 201, embed.text
    embed = embed.json()
    listed = {item['id']: item['model_type'] for item in client.get(path).json()['providers'][0]['models']}
    assert listed == {chat['id']: 'chat', embed['id']: 'embedding'}
    # The type is fixed for the profile; an edit that names another type is a conflict, not a silent change.
    changed = client.put(path + '/providers/' + provider['id'] + '/models/' + embed['id'], json={'name': 'embed-model', 'model_type': 'chat'})
    assert changed.status_code == 409
    # A default slot only accepts a model of its own type.
    assert client.put(path + '/default', json={'scope': 'tenant', 'model_type': 'chat', 'version_id': embed['version_id']}).status_code == 409
    assert client.put(path + '/default', json={'scope': 'tenant', 'model_type': 'embedding', 'version_id': embed['version_id']}).status_code == 200
    assert client.put(path + '/default', json={'scope': 'tenant', 'model_type': 'chat', 'version_id': chat['version_id']}).status_code == 200
    defaults = client.get(path).json()['defaults']
    assert defaults == {'tenant': {'chat': chat['version_id'], 'embedding': embed['version_id']}}
    assert client.put(path + '/default', json={'scope': 'tenant', 'model_type': 'embedding', 'version_id': None}).status_code == 200
    assert client.get(path).json()['defaults'] == {'tenant': {'chat': chat['version_id']}}


def test_draft_connection_test_persists_nothing_and_reports_unsupported_types(settings_client, monkeypatch):
    """Unsaved configurations can be tested; unimplemented probes never reach the supplier."""
    client, path, *_ = settings_client
    import nexus_api.http.model_settings as endpoint
    calls = []
    class Fake:
        def __init__(self, **kwargs): calls.append(kwargs)
        async def stream(self, request):
            yield
        async def close(self): pass
    monkeypatch.setattr(endpoint, 'OpenAICompatibleModel', Fake)
    monkeypatch.setattr(endpoint, 'provider_client', lambda *a, **kw: None)
    before = len(client.get(path).json()['providers'])
    body = {'base_url': 'https://model.example/v1', 'model_name': 'draft-model', 'api_key': 'draft-private-key', 'scope': 'personal'}
    ok = client.post(path + '/test', json=body)
    assert ok.json() == {'ok': True, 'message': '连接成功，流式响应正常'}
    assert calls and calls[-1]['api_key'] == 'draft-private-key'
    assert 'draft-private-key' not in ok.text
    assert len(client.get(path).json()['providers']) == before
    # Rate limit applies to draft tests per user, like saved-model tests.
    assert client.post(path + '/test', json=body).status_code == 409
    skipped = client.post(path + '/test', json={**body, 'model_type': 'vision'})
    assert skipped.status_code == 409  # still inside the cooldown window, so the limit is checked first
    endpoint.draft_test_started.clear()
    before_calls = len(calls)
    skipped = client.post(path + '/test', json={**body, 'model_type': 'vision'})
    assert skipped.json()['code'] == 'unsupported_for_type'
    assert len(calls) == before_calls


def test_enterprise_model_copy_keeps_model_id_and_provider_but_creates_a_distinct_version(settings_client, database):
    client, path, identity, owner, member, _ = settings_client
    admin_path = path.replace('/model-settings', '/admin/model-settings')
    shared = add_provider(client, path, scope='tenant')
    personal = add_provider(client, path)
    source_route = f'/providers/{shared["id"]}/models'
    model = client.post(path + source_route, json={
        'name': 'upstream-id', 'display_name': 'Readable label',
        'model_type': 'rerank', 'options': {'rerank_api': 'tei'},
    }).json()
    personal_model = add_model(client, path, personal)
    assert client.put(path + '/default', json={
        'scope': 'tenant', 'model_type': 'rerank', 'version_id': model['version_id'],
    }).status_code == 200
    route = admin_path + source_route + '/' + model['id'] + '/copy'
    identity[0] = member
    assert client.post(route, json={}).status_code == 403
    identity[0] = owner
    assert client.post(f'{admin_path}/providers/{personal["id"]}/models/{personal_model["id"]}/copy', json={}).status_code == 404
    results = [client.post(route, json={'suffix': '副本'}) for _ in range(2)]
    assert all(result.status_code == 201 for result in results)
    listed = client.get(admin_path).json()
    assert listed['defaults']['tenant'] == {'rerank': model['version_id']}
    rows = next(provider['models'] for provider in listed['providers'] if provider['id'] == shared['id'])
    assert {row['display_name'] for row in rows} == {'Readable label', 'Readable label 副本', 'Readable label 副本 2'}
    assert all(row['name'] == 'upstream-id' and row['version'] == 1 and row['options']['rerank_api'] == 'tei' for row in rows)
    assert len({row['id'] for row in rows}) == 3
    with database() as db:
        versions = [db.get(ModelProfileVersionRecord, UUID(row['version_id'])) for row in rows]
        assert len({version.credential_reference_id for version in versions}) == 1


def test_enterprise_model_and_provider_are_created_in_one_transaction(settings_client, database, monkeypatch):
    from nexus_platform.models import provider_settings

    client, path, identity, owner, member, _ = settings_client
    route = path.replace('/model-settings', '/admin/model-settings') + '/models'
    body = {
        'name': 'model-id', 'display_name': 'My model',
        'provider': {'name': 'Gateway', 'base_url': 'https://model.example/v1', 'api_key': 'first-model-secret'},
    }
    identity[0] = member
    assert client.post(route, json=body).status_code == 403
    identity[0] = owner

    def fail_version(*args, **kwargs):
        raise ValueError('Model version rejected')

    with monkeypatch.context() as patch:
        patch.setattr(provider_settings, 'new_version', fail_version)
        assert client.post(route, json=body).status_code == 422
    assert client.get(path).json()['providers'] == []
    with database() as db:
        assert db.scalar(select(ProviderCredentialRecord)) is None

    created = client.post(route, json=body)
    assert created.status_code == 201
    assert 'first-model-secret' not in created.text
    catalog = client.get(path)
    assert 'first-model-secret' not in catalog.text
    provider, = catalog.json()['providers']
    model, = provider['models']
    assert (provider['name'], provider['scope']) == ('Gateway', 'tenant')
    assert (model['id'], model['version_id']) == (created.json()['id'], created.json()['version_id'])
    assert (model['name'], model['display_name']) == ('model-id', 'My model')


@pytest.mark.parametrize(('model_type', 'adapter_module', 'response', 'expected_path'), [
    ('embedding', 'embeddings', {'data': [{'index': 0, 'embedding': [0.1, 0.2]}]}, '/v1/embeddings'),
    ('rerank', 'rerank', {'results': [{'index': 0, 'relevance_score': 0.5}]}, '/v1/rerank'),
])
def test_enterprise_connection_probes_use_configured_adapter(
    settings_client, monkeypatch, model_type, adapter_module, response, expected_path,
):
    from importlib import import_module
    client, path, *_ = settings_client
    provider = add_provider(client, path, scope='tenant')
    admin_path = path.replace('/model-settings', '/admin/model-settings')
    adapter = import_module(f'nexus_runtimes.native.models.{adapter_module}')
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.url.path == expected_path
        assert request.headers['Authorization'] == 'Bearer test-private-key'
        return httpx.Response(200, json=response)

    monkeypatch.setattr(adapter, 'provider_client', lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    draft = {'provider_id': provider['id'], 'model_name': 'probe-model', 'model_type': model_type,
             'scope': 'tenant', 'base_url': provider['base_url']}
    result = client.post(admin_path + '/test', json=draft)
    assert result.status_code == 200
    assert result.json()['ok'] is True
    assert set(result.json()) == {'ok', 'message'}
    assert 'test-private-key' not in result.text
    assert len(calls) == 1
    assert client.post(admin_path + '/test', json=draft).status_code == 409
    assert client.get(path).json()['providers'][0]['models'] == []


@pytest.mark.parametrize(('status', 'code'), [
    (404, 'model_request_rejected'), (401, 'model_authentication_failed'),
    (429, 'model_rate_limited'), (503, 'model_provider_unavailable'),
    (None, 'model_timeout'),
])
def test_embedding_probe_preserves_safe_failure_diagnosis(monkeypatch, status, code):
    from nexus_api.http.model_settings import check_connection
    from nexus_runtimes.native.models import embeddings

    def upstream(request):
        assert request.url.path == '/embeddings'
        if status is None:
            raise httpx.ReadTimeout('upstream-secret', request=request)
        return httpx.Response(status, json={'error': {'message': 'upstream-secret'}})

    monkeypatch.setattr(embeddings, 'provider_client',
                        lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    result = asyncio.run(check_connection(key='test-key', base_url='https://model.example',
                                          model_name='test-embedding', options={}, model_type='embedding'))
    assert result['ok'] is False
    assert result['code'] == code
    assert 'upstream-secret' not in result['message']
    if status == 404:
        assert '/embeddings' in result['message'] and '向量模型 ID' in result['message']


def test_draft_test_requires_a_key_for_new_providers_and_scope_permission(settings_client):
    client, path, identity, owner, member, _ = settings_client
    missing = client.post(path + '/test', json={'base_url': 'https://model.example/v1', 'model_name': 'm', 'scope': 'personal'})
    assert missing.status_code == 422
    assert 'API Key is required' in missing.text
    identity[0] = member
    denied = client.post(path + '/test', json={'base_url': 'https://model.example/v1', 'model_name': 'm', 'scope': 'tenant', 'api_key': 'k'})
    assert denied.status_code == 403
    assert 'k' not in denied.text


def test_enterprise_model_connection_edit_changes_only_selected_profile(settings_client, database):
    client, path, _, _, _, tenant_id = settings_client
    provider = add_provider(client, path, scope='tenant')
    model = add_model(client, path, provider)
    sibling = add_model(client, path, provider, 'sibling')
    admin = path.replace('/model-settings', '/admin/model-settings')
    route = f'{admin}/providers/{provider["id"]}/models/{model["id"]}/configuration'
    payload = {'name': 'new-upstream', 'model_type': 'chat', 'provider': {
        'name': 'Replacement', 'base_url': 'https://new.example/v1', 'scope': 'tenant',
    }}
    assert client.put(route, json=payload).status_code == 422
    payload['provider']['api_key'] = 'replacement-key'
    response = client.put(route, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['id'] == model['id']
    assert 'replacement-key' not in response.text
    groups = client.get(admin).json()['providers']
    by_name = {group['name']: group for group in groups}
    assert [row['id'] for row in by_name['Provider']['models']] == [sibling['id']]
    assert [row['id'] for row in by_name['Replacement']['models']] == [model['id']]
    with database() as db:
        old = db.get(ModelProfileVersionRecord, UUID(model['version_id']))
        other = db.get(ModelProfileVersionRecord, UUID(sibling['version_id']))
        new = db.get(ModelProfileVersionRecord, UUID(response.json()['version_id']))
        assert old.tenant_id == new.tenant_id == tenant_id
        assert old.options['base_url'] == 'https://model.example/v1'
        assert new.options['base_url'] == 'https://new.example/v1'
        assert old.credential_reference_id == other.credential_reference_id != new.credential_reference_id
        assert decrypt(db.get(ProviderCredentialRecord, old.credential_reference_id)) == 'test-private-key'
        assert decrypt(db.get(ProviderCredentialRecord, new.credential_reference_id)) == 'replacement-key'


def test_enterprise_model_delete_reports_active_references(settings_client, database):
    from nexus_platform.persistence.models import KnowledgeBaseRecord

    client, path, _, owner, _, tenant_id = settings_client
    provider = add_provider(client, path, scope='tenant')
    model = add_model(client, path, provider)
    assert client.put(path + '/default', json={'scope': 'tenant', 'version_id': model['version_id']}).status_code == 200
    agent = client.post(path + '/agents', json={'name': 'Private agent'})
    assert agent.status_code == 201, agent.text
    with database() as db, db.begin():
        user = resolve_user(db, owner)
        now = utc_now()
        db.add(KnowledgeBaseRecord(id=new_id(), tenant_id=tenant_id, name='Private knowledge base', created_by=user.id,
                                   settings={'summary_model_id': model['version_id']}, created_at=now, updated_at=now))
    admin = path.replace('/model-settings', '/admin/model-settings')
    route = f'{admin}/providers/{provider["id"]}/models/{model["id"]}/configuration'
    response = client.delete(route)
    assert response.status_code == 409
    issue = response.json()['error']
    assert issue['code'] == 'model_in_use'
    assert issue['details'] == {'agents': 1, 'knowledge_bases': 1, 'memory': 0}
    assert 'Private agent' not in response.text
    assert 'Private knowledge base' not in response.text


def test_enterprise_model_debug_uses_current_model_and_redacts_credential(settings_client, monkeypatch):
    from nexus_api.http import model_settings
    from nexus_core.runtime import ModelChunk

    class DebugAdapter:
        closed = False

        async def stream(self, request):
            assert request.messages[-1].content == 'debug prompt'
            assert request.max_output_tokens == 256
            yield ModelChunk('text', text='result test-private-key')
            yield ModelChunk('done', finish_reason='stop')

        async def close(self):
            self.closed = True

    adapter = DebugAdapter()

    def factory(**arguments):
        assert arguments['model'] == 'test-model'
        assert arguments['api_key'] == 'test-private-key'
        assert arguments['options']['temperature'] == 0
        return adapter

    monkeypatch.setattr(model_settings, 'create_model', factory)
    client, path, *_ = settings_client
    provider = add_provider(client, path, scope='tenant')
    model = add_model(client, path, provider)
    admin = path.replace('/model-settings', '/admin/model-settings')
    route = f'{admin}/providers/{provider["id"]}/models/{model["id"]}/debug'
    payload = {'text': 'debug prompt', 'max_output_tokens': 256, 'temperature': 0}
    response = client.post(route, json=payload)
    assert response.status_code == 200, response.text
    assert response.json() == {'ok': True, 'result': {'type': 'chat', 'text': 'result [redacted]'}}
    assert adapter.closed
    assert client.post(route, json=payload).status_code == 409


@pytest.mark.parametrize('model_type,filename,expected', [
    ('vision', 'sample.png', 'image/png'),
    ('speech', 'sample.wav', 'sample.wav'),
])
def test_enterprise_media_debug_uses_saved_model_without_storing_upload(
    settings_client, monkeypatch, model_type, filename, expected,
):
    from nexus_api.http import model_settings

    class Adapter:
        closed = False

        async def describe(self, data, mime, system, prompt, max_tokens):
            assert (data, mime, prompt) == (b'test media', expected, 'Describe the sample')
            return 'media response'

        async def transcribe(self, data, name):
            assert (data, name) == (b'test media', expected)
            return 'media response'

        async def close(self):
            self.closed = True

    adapter = Adapter()
    factory = 'create_vision' if model_type == 'vision' else 'create_transcriber'
    monkeypatch.setattr(model_settings, factory, lambda **_: adapter)
    client, path, *_ = settings_client
    provider = add_provider(client, path, scope='tenant')
    model = client.post(f'{path}/providers/{provider["id"]}/models',
                        json={'name': 'test-media', 'model_type': model_type}).json()
    admin = path.replace('/model-settings', '/admin/model-settings')
    route = f'{admin}/providers/{provider["id"]}/models/{model["id"]}/debug-media'
    response = client.post(route, files={'file': (filename, b'test media')}, data={'text': 'Describe the sample'})
    assert response.status_code == 200, response.text
    assert response.json() == {'ok': True, 'result': {'type': model_type, 'text': 'media response'}}
    assert adapter.closed
