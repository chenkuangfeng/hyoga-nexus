"""HTTP skill endpoints: publish, list and version metadata; bodies are never returned (proposal 7.1, task 5.x).

Uses the same settings client as the native API tests: development auth with an identity override.
"""
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _tenant

SKILL = '---\nname: api-skill\ndescription: Via HTTP\ntools: []\n---\nSECRET-BODY-TEXT\n'


def _client(database, principal):
    def session():
        with database() as db:
            yield db
            db.commit()
    app.dependency_overrides[get_principal] = lambda: principal
    app.dependency_overrides[get_database_session] = session
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_publish_list_and_versions_without_exposing_the_body(database):
    tenant, _ = _tenant(database)
    client = _client(database, PRINCIPAL)
    base = f'/api/v1/tenants/{tenant.id}/skills'
    created = client.post(base, json={'skill_md': SKILL, 'files': {'refs/a.md': 'note'}})
    assert created.status_code == 201, created.text
    assert created.json()['version'] == 1 and 'SECRET-BODY-TEXT' not in created.text
    listed = client.get(base).json()
    assert [row['name'] for row in listed] == ['api-skill'] and listed[0]['version'] == 1
    versions = client.get(base + '/api-skill/versions').json()
    assert versions[0]['content_hash'] == created.json()['content_hash']
    assert 'SECRET-BODY-TEXT' not in client.get(base + '/api-skill/versions').text


def test_invalid_skill_is_a_client_error_with_a_stable_code(database):
    tenant, _ = _tenant(database)
    client = _client(database, PRINCIPAL)
    response = client.post(f'/api/v1/tenants/{tenant.id}/skills', json={'skill_md': 'no frontmatter'})
    assert response.status_code >= 400 and 'frontmatter_missing' in response.text
