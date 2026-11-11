"""Artifact endpoints (openspec 2026-11-07-tool-expansion 4.6)."""
import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_platform.artifacts import service
from test_artifacts import register, run_of  # noqa: F401  (fixture and helper)
from test_platform import database  # noqa: F401  (fixture)
from test_schedule_rest_service import MEMBER, OTHER_MEMBER, OWNER, STRANGER, world  # noqa: F401  (fixtures and people)


@pytest.fixture
def api(run_of, monkeypatch):
    ctx = run_of
    monkeypatch.setattr(service, 'artifacts_root', lambda: ctx['root'])

    def session():
        with ctx['factory']() as db:
            yield db

    who = [MEMBER]
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: who[0]
    try:
        with TestClient(app) as client:
            client.base = f"/api/v1/tenants/{ctx['tenant_id']}/artifacts"
            client.ctx = ctx
            client.as_ = lambda principal: who.__setitem__(0, principal)
            yield client
    finally:
        app.dependency_overrides.clear()


def make(api, name='report.txt', content='hello'):
    (api.ctx['outputs'] / name).write_text(content, encoding='utf-8')
    return [a for a in register(api.ctx)['registered'] if a['name'] == name][0]


def test_list_get_download_delete(api):
    artifact = make(api)
    listed = api.get(api.base).json()['items']
    assert [item['id'] for item in listed] == [artifact['id']] and listed[0]['path'] == '/outputs/report.txt'
    assert api.get(f"{api.base}?session_id={api.ctx['session_id']}").json()['items'][0]['id'] == artifact['id']
    assert api.get(f"{api.base}?run_id={api.ctx['run_id']}").json()['items'][0]['id'] == artifact['id']
    assert api.get(f"{api.base}/{artifact['id']}").json()['sha256'] == artifact['sha256']

    downloaded = api.get(f"{api.base}/{artifact['id']}/download")
    assert downloaded.status_code == 200 and downloaded.content == b'hello'
    assert 'attachment' in downloaded.headers['content-disposition'] and 'report.txt' in downloaded.headers['content-disposition']
    assert downloaded.headers['x-content-type-options'] == 'nosniff'
    assert downloaded.headers['content-type'].startswith('application/octet-stream')

    assert api.delete(f"{api.base}/{artifact['id']}").status_code == 204
    assert api.get(f"{api.base}/{artifact['id']}").status_code == 404
    assert api.get(f"{api.base}/{artifact['id']}/download").status_code == 404
    assert api.get(api.base).json()['items'] == []


def test_a_page_is_never_served_as_a_page(api):
    artifact = make(api, 'page.html', '<script>alert(1)</script>')
    downloaded = api.get(f"{api.base}/{artifact['id']}/download")
    assert downloaded.headers['content-type'].startswith('application/octet-stream')
    assert 'attachment' in downloaded.headers['content-disposition']


def test_visibility_follows_the_session(api):
    artifact = make(api)
    api.as_(OTHER_MEMBER)
    assert api.get(api.base).json()['items'] == []
    assert api.get(f"{api.base}/{artifact['id']}").status_code == 404
    assert api.get(f"{api.base}/{artifact['id']}/download").status_code == 404
    assert api.delete(f"{api.base}/{artifact['id']}").status_code == 404

    api.as_(OWNER)  # a space owner sees everything in the space
    assert [i['id'] for i in api.get(api.base).json()['items']] == [artifact['id']]
    assert api.get(f"{api.base}/{artifact['id']}/download").content == b'hello'

    api.as_(STRANGER)
    assert api.get(api.base).status_code in (403, 404)
    assert api.get(f"{api.base}/{artifact['id']}/download").status_code in (403, 404)


def test_validation_and_a_missing_copy(api):
    assert api.get(f'{api.base}?limit=0').status_code == 422
    assert api.get(f'{api.base}/not-a-uuid').status_code == 422
    artifact = make(api)
    (api.ctx['root'] / str(api.ctx['tenant_id']) / artifact['id']).unlink()
    assert api.get(f"{api.base}/{artifact['id']}/download").status_code == 404


def test_the_library_parameters_and_totals(api):
    make(api, 'plan.pdf', 'p')
    make(api, 'notes.md', 'n')
    everything = api.get(api.base).json()
    assert everything['total'] == 2 and {i['session_title'] for i in everything['items']} == {'Work'}
    only_pdf = api.get(f'{api.base}?extensions=.pdf,.docx').json()
    assert [i['name'] for i in only_pdf['items']] == ['plan.pdf'] and only_pdf['total'] == 1
    assert [i['name'] for i in api.get(f'{api.base}?q=NOTE').json()['items']] == ['notes.md']
    latest = api.get(f'{api.base}?latest=true').json()['items']
    assert all(item['version_count'] == 1 for item in latest)
    assert api.get(f"{api.base}?q={'x' * 201}").status_code == 422


def test_delete_with_all_versions(api):
    first = make(api, 'a.txt', 'one')
    from test_artifacts import _next_run
    (api.ctx['outputs'] / 'a.txt').write_text('two', encoding='utf-8')
    register(api.ctx, run_id=_next_run(api.ctx))
    assert api.get(f'{api.base}?latest=true').json()['total'] == 1
    assert api.get(api.base).json()['total'] == 2
    assert api.delete(f"{api.base}/{first['id']}?all_versions=true").status_code == 204
    assert api.get(api.base).json()['total'] == 0
