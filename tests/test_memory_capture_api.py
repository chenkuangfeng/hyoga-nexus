"""HTTP contract for automatic memory capture settings: off by default, enabling needs a capture model
(openspec 2026-11-01-memory-optimization, stage 3.5/3.6)."""
from nexus_platform.models.service import create_model_profile

from test_model_settings import settings_client  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)


def test_capture_settings_are_off_by_default_and_enabling_needs_a_capture_model(settings_client, database):  # noqa: F811
    client, path, identity, owner, member, tenant_id = settings_client
    root = path.removesuffix('/model-settings') + '/native'
    assert client.get(root + '/memory-capture').json() == {
        'enabled': False, 'model_profile_version_id': None, 'capacity_policy': 'reject'}

    # Enabling without a model is refused.
    assert client.put(root + '/memory-capture', json={'enabled': True}).status_code == 422

    with database() as db:
        _, version = create_model_profile(db, owner, tenant_id, name='capture', provider='test',
                                          model_name='fake', options={})
        version_id = str(version.id)
    response = client.put(root + '/memory-capture', json={
        'enabled': True, 'model_profile_version_id': version_id, 'capacity_policy': 'evict_auto'})
    assert response.status_code == 200
    assert response.json() == {'enabled': True, 'model_profile_version_id': version_id,
                               'capacity_policy': 'evict_auto'}
    assert client.get(root + '/memory-capture').json()['enabled'] is True

    assert client.put(root + '/memory-capture', json={'enabled': False, 'capacity_policy': 'drop_all'}).status_code == 422
    assert client.put(root + '/memory-capture', json={'enabled': False}).json()['enabled'] is False
