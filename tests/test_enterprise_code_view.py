"""Enterprise metadata exposes the registered code without changing tenant authorization or writes."""
import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole
from nexus_platform.persistence.models import TenantRecord
from nexus_platform.tenants.service import add_member, create_tenant
from test_platform import database  # noqa: F401


@pytest.fixture
def code_api(database):
    actor = {'value': Principal('code-owner', 'test')}
    with database() as db:
        tenant_id = create_tenant(db, actor['value'], 'Acme').id
    def get_db():
        with database() as db:
            yield db
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_database_session] = get_db
    app.dependency_overrides[get_principal] = lambda: actor['value']
    client = TestClient(app)
    try:
        yield client, database, actor, tenant_id
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize('code', ['acme_01', None])
def test_code_is_returned_consistently_and_remains_read_only(code_api, code):
    client, factory, actor, tenant_id = code_api
    with factory() as db, db.begin():
        db.get(TenantRecord, tenant_id).code = code
    headers = {'X-Tenant-ID': str(tenant_id)}
    for path in ('/api/v1/tenants/current', f'/api/v1/tenants/{tenant_id}/admin'):
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.json()['code'] == code
        updated = client.patch(path, headers=headers, json={'name': 'New name', 'code': 'overwrite'})
        assert updated.status_code == 200
        assert updated.json()['code'] == code
    listed = client.get('/api/v1/tenants').json()
    assert next(row for row in listed if row['id'] == str(tenant_id))['code'] == code
    with factory() as db:
        assert db.get(TenantRecord, tenant_id).code == code


def test_code_read_keeps_existing_member_and_outsider_boundaries(code_api):
    client, factory, actor, tenant_id = code_api
    viewer = Principal('code-viewer', 'test')
    with factory() as db:
        add_member(db, actor['value'], tenant_id, viewer, TenantRole.VIEWER)
    actor['value'] = viewer
    path = f'/api/v1/tenants/{tenant_id}/admin'
    assert client.get(path).status_code == 200
    assert client.patch(path, json={'name': 'Unauthorized'}).status_code == 403
    actor['value'] = Principal('code-outsider', 'test')
    assert client.get(path).status_code == 404
