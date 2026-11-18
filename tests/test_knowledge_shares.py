"""Sharing enterprise knowledge bases with shared spaces (openspec 2026-11-06-knowledge-base K1.9a/K1.9b).

Same effective-level rule as agent shares; any effective level reads, and only the owning space manages shares.
"""
from test_agent_shares import _as, _register, _world  # noqa: F401
from test_agent_shares import client  # noqa: F401  (fixture)
from test_platform import database  # noqa: F401  (fixture)


def _kb(client, w, name='手册'):
    created = client.post(f"/api/v1/tenants/{w['acme']}/admin/knowledge/bases", headers=_as(w['ann'], w['acme']),
                          json={'name': name, 'visibility': 'tenant', 'indexing_strategy': {'vector': False, 'keyword': True}})
    assert created.status_code == 201, created.text
    return created.json()['id']


def _share(client, w, kb, level='viewer'):
    return client.post(f"/api/v1/tenants/{w['acme']}/knowledge/bases/{kb}/shares", headers=_as(w['ann'], w['acme']),
                       json={'shared_space_id': w['shared'], 'level': level})


def test_share_change_level_and_unshare(client):
    w = _world(client)
    kb = _kb(client, w)
    assert client.get(f"/api/v1/tenants/{w['beta']}/knowledge/bases/{kb}", headers=_as(w['bea'], w['beta'])).status_code == 404

    created = _share(client, w, kb)
    assert created.status_code == 201, created.text
    assert created.json()['level'] == 'viewer' and created.json()['shared_space_name'] == 'Alliance'
    assert _share(client, w, kb, 'editor').json()['level'] == 'editor'  # same row, new level

    listed = client.get(f"/api/v1/tenants/{w['acme']}/knowledge/bases/{kb}/shares", headers=_as(w['ann'], w['acme']))
    assert [(i['shared_space_id'], i['level']) for i in listed.json()['items']] == [(w['shared'], 'editor')]

    removed = client.delete(f"/api/v1/tenants/{w['acme']}/knowledge/bases/{kb}/shares/{w['shared']}",
                            headers=_as(w['ann'], w['acme']))
    assert removed.status_code == 204
    assert client.get(f"/api/v1/tenants/{w['beta']}/knowledge/bases/{kb}", headers=_as(w['bea'], w['beta'])).status_code == 404
    again = client.delete(f"/api/v1/tenants/{w['acme']}/knowledge/bases/{kb}/shares/{w['shared']}",
                          headers=_as(w['ann'], w['acme']))
    assert again.status_code == 404


def test_member_space_reads_but_cannot_change_or_reshare(client):
    w = _world(client)
    kb = _kb(client, w)
    _share(client, w, kb, 'admin')
    bea = _as(w['bea'], w['beta'])
    base = f"/api/v1/tenants/{w['beta']}/knowledge"

    seen = client.get(f'{base}/bases/{kb}', headers=bea)
    assert seen.status_code == 200 and seen.json()['shared'] is True and seen.json()['can_edit'] is False
    assert kb in [b['id'] for b in client.get(f'{base}/bases', headers=bea).json()['items']]

    shared = client.get(f'{base}/shared-bases', headers=bea).json()['items']
    assert [(i['id'], i['owner_tenant_name']) for i in shared] == [(kb, 'Acme')] and shared[0]['level'] == 'editor'  # min(admin, Beta's role editor)

    assert client.patch(f'{base}/bases/{kb}', headers=bea, json={'name': 'x'}).status_code in (403, 404)
    assert client.delete(f'{base}/bases/{kb}', headers=bea).status_code in (403, 404)
    # Managing shares is for the owning space only.
    assert client.get(f'{base}/bases/{kb}/shares', headers=bea).status_code == 404
    assert client.post(f'{base}/bases/{kb}/shares', headers=bea,
                       json={'shared_space_id': w['shared'], 'level': 'viewer'}).status_code == 404


def test_only_owning_managers_share_and_into_spaces_they_belong_to(client):
    w = _world(client)
    kb = _kb(client, w)
    # A space that does not own the base cannot share it.
    assert client.post(f"/api/v1/tenants/{w['beta']}/knowledge/bases/{kb}/shares", headers=_as(w['bea'], w['beta']),
                       json={'shared_space_id': w['shared'], 'level': 'viewer'}).status_code == 404
    # The owner cannot share into a shared space its space is not a member of.
    other, other_space = _register(client, 'oscar', 'enterprise', 'Third', 'third-kbs')
    foreign = client.post('/api/v1/shared-spaces', json={'name': 'Foreign'}, headers=_as(other, other_space)).json()['id']
    assert client.post(f"/api/v1/tenants/{w['acme']}/knowledge/bases/{kb}/shares", headers=_as(w['ann'], w['acme']),
                       json={'shared_space_id': foreign, 'level': 'viewer'}).status_code == 403
    # Invalid levels are rejected before anything is stored.
    assert _share(client, w, kb, 'owner').status_code == 422
    # Personal spaces cannot share.
    solo, solo_space = _register(client, 'solo')
    assert client.post(f'/api/v1/tenants/{solo_space}/knowledge/bases/{kb}/shares', headers=_as(solo, solo_space),
                       json={'shared_space_id': w['shared'], 'level': 'viewer'}).status_code == 404


def test_deleted_bases_and_outsiders_see_nothing(client):
    w = _world(client)
    kb = _kb(client, w)
    _share(client, w, kb)
    outsider, outsider_space = _register(client, 'olga', 'enterprise', 'Outside', 'out-kbs')
    assert client.get(f'/api/v1/tenants/{outsider_space}/knowledge/shared-bases',
                      headers=_as(outsider, outsider_space)).json()['items'] == []
    assert client.get(f'/api/v1/tenants/{outsider_space}/knowledge/bases/{kb}',
                      headers=_as(outsider, outsider_space)).status_code == 404
    assert client.delete(f"/api/v1/tenants/{w['acme']}/knowledge/bases/{kb}",
                         headers=_as(w['ann'], w['acme'])).status_code == 204
    assert client.get(f"/api/v1/tenants/{w['beta']}/knowledge/shared-bases",
                      headers=_as(w['bea'], w['beta'])).json()['items'] == []
