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
from nexus_core.platform import Principal, utc_now, CredentialRef
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
def settings_client(database, monkeypatch):
    monkeypatch.setenv('NEXUS_CREDENTIAL_ENCRYPTION_KEY', Fernet.generate_key().decode())
    owner = Principal('settings-owner', 'test')
    member = Principal('settings-member', 'test')
    with database() as db:
        tenant = create_tenant(db, owner, 'Settings')
        with db.begin():
            user = resolve_user(db, member)
            db.add(MembershipRecord(tenant_id=tenant.id, user_id=user.id, role='member', status='active', joined_at=utc_now()))
    identity = [owner]
    def session():
        with database() as db:
            yield db
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: identity[0]
    with TestClient(app) as client:
        yield client, '/api/v1/tenants/' + str(tenant.id) + '/model-settings', identity, owner, member, tenant.id
    app.dependency_overrides.clear()


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
    created = client.post(path + '/agents', json={'name': 'Member agent'})
    assert created.status_code == 201, created.text


def test_missing_key_invalid_input_and_key_not_reflected(settings_client, monkeypatch):
    client, path, *_ = settings_client
    monkeypatch.delenv('NEXUS_CREDENTIAL_ENCRYPTION_KEY')
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


def test_credential_integrity_and_legacy_api_cannot_bypass_scope(settings_client, database, monkeypatch):
    client, path, identity, owner, member, tenant_id = settings_client
    provider = add_provider(client, path)
    model = add_model(client, path, provider)
    with database() as db:
        secret = db.scalar(select(ProviderCredentialRecord))
        credential_id = str(secret.credential_id)
        assert decrypt(secret) == 'test-private-key'
        monkeypatch.setenv('NEXUS_CREDENTIAL_ENCRYPTION_KEY', Fernet.generate_key().decode())
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
    assert client.get(path).json()['defaults']['tenant'] == updated['version_id']
    identity[0] = member
    assert client.post(path + '/agents', json={'name': 'Use space default'}).status_code == 201
    assert client.put(path + '/default', json={'version_id': updated['version_id']}).status_code == 200
    assert client.put(path + '/default', json={'version_id': None}).status_code == 200
    assert 'personal' not in client.get(path).json()['defaults']
