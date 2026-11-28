"""HTTP contract for memory availability (enable/disable and validity end) on the owner's entries."""
from nexus_platform.identity.service import resolve_user
from nexus_platform.memory.repository import SqlMemoryRepository

from test_model_settings import settings_client  # noqa: F401 (pytest fixture)
from test_native_runtime import stack
from test_platform import database  # noqa: F401 (pytest fixture)


def test_owner_can_disable_and_set_validity_while_others_get_not_found(settings_client, database):  # noqa: F811
    client, path, identity, owner, member, tenant_id = settings_client
    root = path.removesuffix('/model-settings') + '/native'
    _, _, _, run, _ = stack(database, [])
    with database() as db:
        with db.begin():
            user = resolve_user(db, owner)
            repo = SqlMemoryRepository(db)
            draft = repo.create_draft(tenant_id=tenant_id, source_run_id=run.id, kind='memory', diff='api fact',
                                      fingerprint='a' * 64, base_version=None, origin='foreground',
                                      source_message_ids=())
            entry = repo.create_entry(tenant_id=tenant_id, owner_id=user.id, kind='memory', title='Api', project='')
            repo.append_version(entry_id=entry.id, version=1, content='api fact', source_run_id=run.id,
                                source_draft_id=draft, reviewer_id=user.id, fingerprint='a' * 64,
                                source_message_ids=())
            entry_id = str(entry.id)

    assert client.patch(root + '/memory/' + entry_id, json={'enabled': False}).json()['enabled'] is False
    listed = {item['id']: item for item in client.get(root + '/memory').json()['entries']}
    assert listed[entry_id]['enabled'] is False

    response = client.patch(root + '/memory/' + entry_id, json={'valid_until': '2020-01-01T00:00:00+08:00'})
    assert response.status_code == 200
    listed = {item['id']: item for item in client.get(root + '/memory').json()['entries']}
    assert listed[entry_id]['valid_until'] is not None and listed[entry_id]['enabled'] is False

    # An omitted field is left unchanged; an explicit null clears the validity end.
    client.patch(root + '/memory/' + entry_id, json={'valid_until': None})
    listed = {item['id']: item for item in client.get(root + '/memory').json()['entries']}
    assert listed[entry_id]['valid_until'] is None and listed[entry_id]['enabled'] is False

    identity[0] = member
    assert client.patch(root + '/memory/' + entry_id, json={'enabled': True}).status_code == 404
    identity[0] = owner
    assert client.get(root + '/memory/' + entry_id).status_code == 200


def test_manual_memory_needs_no_run_and_retains_owner_isolation(settings_client, database):  # noqa: F811
    client, path, identity, owner, member, tenant_id = settings_client
    root = path.removesuffix('/model-settings') + '/native'
    body = {'title': '回复偏好', 'kind': 'profile', 'content': '我喜欢用中文交流并提供简洁的说明。', 'importance': 4}
    response = client.post(root + '/memory', json=body)
    assert response.status_code == 201, response.text
    entry_id = response.json()['id']
    read = client.get(root + '/memory/' + entry_id)
    assert read.status_code == 200
    assert read.json()['content'] == body['content']
    assert client.post(root + '/memory', json=body).status_code == 409
    assert client.post(root + '/memory', json={**body, 'content': '   '}).status_code == 422
    assert client.post(root + '/memory', json={**body, 'kind': 'unknown'}).status_code == 422
    identity[0] = member
    assert client.get(root + '/memory/' + entry_id).status_code == 404
    assert client.delete(root + '/memory/' + entry_id).status_code == 404
    identity[0] = owner
    assert client.delete(root + '/memory/' + entry_id).status_code == 200
    assert all(row['id'] != entry_id for row in client.get(root + '/memory').json()['entries'])


def test_manual_memory_budget_failure_rolls_back_draft(settings_client):
    client, path, *_ = settings_client
    root = path.removesuffix('/model-settings') + '/native'
    body = {'title': '内容', 'kind': 'memory'}
    assert client.post(root + '/memory', json={**body, 'content': 'x' * 6001}).status_code == 409
    assert client.get(root + '/memory').json() == {'entries': [], 'drafts': []}


def test_manual_memory_can_be_consolidated_without_fabricated_run(settings_client, database):  # noqa: F811
    from nexus_memory import service as rules

    client, path, identity, owner, member, tenant_id = settings_client
    root = path.removesuffix('/model-settings') + '/native'
    for title, content in [('语言', '我喜欢用中文交流。'), ('说明', '我喜欢简洁的说明。')]:
        assert client.post(root + '/memory', json={'title': title, 'content': content}).status_code == 201
    with database() as db:
        with db.begin():
            user = resolve_user(db, owner)
            repo = SqlMemoryRepository(db)
            entries = repo.live_entries(tenant_id, user.id)
            proposal = rules.propose_merge(repo, tenant_id, user.id, keep=entries[0], others=[entries[1]],
                                           merged='我喜欢用中文交流，并希望说明简洁。')
    assert proposal['status'] == 'pending'
    assert len(client.get(root + '/memory').json()['drafts']) == 1
    identity[0] = member
    assert client.get(root + '/memory').json()['drafts'] == []
    identity[0] = owner
    response = client.post(root + '/memory-drafts/' + proposal['id'] + '/review',
                           json={'approve': True, 'title': '交流偏好'})
    assert response.status_code == 200
    assert len(client.get(root + '/memory').json()['entries']) == 1
