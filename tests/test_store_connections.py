"""Enterprise-configured knowledge stores cannot reach the deployment's disk or private network
(openspec 2026-11-11-enterprise-saas decision 9), and memberships tell the client which apps to open (E2)."""
import pytest

from nexus_platform.errors import InvalidConfiguration
from nexus_platform.knowledge.connections import check_store

from test_auth import PASSWORD, client  # noqa: F401  (fixture)
from test_platform import database  # noqa: F401  (fixture)


def test_file_backed_stores_need_the_deployment_switch(deployment_config):
    deployment_config('')
    with pytest.raises(InvalidConfiguration, match='local_store_not_allowed'):
        check_store('vector', 'sqlite', {'path': '/etc/passwd'})
    with pytest.raises(InvalidConfiguration, match='local_store_not_allowed'):
        check_store('storage', 'local', {'root': '/'})
    deployment_config('[knowledge]\nallow_tenant_local_stores = true\n')
    check_store('vector', 'sqlite', {'path': 'tenant.db'})


@pytest.mark.parametrize('config', [
    {'url': 'http://127.0.0.1:6333'}, {'url': 'http://10.0.0.5'}, {'url': 'http://[::1]:9200'},
    {'dsn': 'postgresql://u:p@192.168.1.10:5432/db'}, {'url': 'http://169.254.169.254/latest'},
])
def test_private_addresses_are_refused_unless_allowlisted(deployment_config, config):
    deployment_config('')
    with pytest.raises(InvalidConfiguration, match='store_destination_denied'):
        check_store('vector', 'qdrant', config)


def test_allowlisted_and_public_hosts_pass(deployment_config):
    deployment_config('[model_network]\nprivate_host_allowlist = ["qdrant.internal", "127.0.0.1"]\n')
    check_store('vector', 'qdrant', {'url': 'http://127.0.0.1:6333'})
    check_store('vector', 'qdrant', {'url': 'http://QDRANT.internal:6333'})
    check_store('graph', 'neo4j', {'url': 'https://8.8.8.8:7473'})


def test_memberships_list_the_apps_each_role_may_open(client):
    client.post('/api/v1/auth/register', json={'username': 'ann', 'email': 'ann@example.com', 'password': PASSWORD})
    login = client.post('/api/v1/auth/login', json={'email': 'ann@example.com', 'password': PASSWORD}).json()
    assert [m['entries'] for m in login['memberships']] == [['workspace', 'enterprise']]
    headers = {'Authorization': f"Bearer {login['token']}", 'X-Tenant-ID': str(login['memberships'][0]['id'])}
    client.post('/api/v1/auth/register', json={'username': 'bob', 'email': 'bob@example.com', 'password': PASSWORD})
    space = login['memberships'][0]['id']
    invited = client.post(f'/api/v1/tenants/{space}/members/by-email', headers=headers,
                          json={'email': 'bob@example.com', 'role': 'contributor'})
    assert invited.status_code in (200, 201), invited.text
    bob = client.post('/api/v1/auth/login', json={'email': 'bob@example.com', 'password': PASSWORD}).json()
    bob_headers = {'Authorization': f"Bearer {bob['token']}"}
    invitation = client.get('/api/v1/me/invitations', headers=bob_headers).json()[0]['id']
    assert client.post(f'/api/v1/me/invitations/{invitation}/accept', headers=bob_headers).status_code == 200
    bob = client.post('/api/v1/auth/login', json={'email': 'bob@example.com', 'password': PASSWORD}).json()
    entries = {str(m['id']): m['entries'] for m in bob['memberships']}
    assert entries[str(space)] == ['workspace']
