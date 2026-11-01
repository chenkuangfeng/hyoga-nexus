"""Publishing snapshots Native behavior, so invalid or unauthorized settings must be refused there (P3, config)."""
import pytest

from nexus_core.platform import Principal
from nexus_platform.agents.service import create_agent, publish_agent
from nexus_platform.errors import InvalidConfiguration, NotFound
from nexus_platform.models.service import create_model_profile
from nexus_platform.tenants.service import create_tenant

from test_platform import database  # noqa: F401 (pytest fixture)


def _setup(factory):
    """Create this tenant's model and another tenant's model; return what a publish test needs."""
    principal = Principal('publish-owner', 'test')
    with factory() as db:
        tenant = create_tenant(db, principal, 'Publish')
        other = create_tenant(db, principal, 'Elsewhere')
        _, model = create_model_profile(db, principal, tenant.id, name='model', provider='test', model_name='fake', options={})
        _, foreign = create_model_profile(db, principal, other.id, name='foreign', provider='test', model_name='fake', options={})
        return principal, tenant.id, model.id, foreign.id


def _publish(factory, principal, tenant_id, model_id, behavior):
    with factory() as db:
        agent = create_agent(db, principal, tenant_id, name='Native', description='', runtime_type='native',
            instructions='x', model_profile_version_id=model_id, budgets={'max_tokens': 1000, 'behavior': behavior}, bindings=[])
        agent_id = agent.id
    with factory() as db:
        return publish_agent(db, principal, tenant_id, agent_id)


def test_a_valid_behavior_publishes(database):
    principal, tenant_id, model_id, _ = _setup(database)
    assert _publish(database, principal, tenant_id, model_id, {'tool_output_inline_limit': 2000})


@pytest.mark.parametrize('behavior', [
    {'tool_output_inline_limit': 5},                        # below the range
    {'compact_low_ratio': 0.9, 'compact_high_ratio': 0.5},  # low above high
    {'tool_preview_chars': 3000},                           # preview larger than the inline limit
    {'unknown_key': 1},                                     # not a Native setting
])
def test_publish_rejects_invalid_native_behavior(database, behavior):
    principal, tenant_id, model_id, _ = _setup(database)
    with pytest.raises(InvalidConfiguration):
        _publish(database, principal, tenant_id, model_id, behavior)


def test_publish_accepts_a_compaction_model_of_the_same_tenant(database):
    principal, tenant_id, model_id, _ = _setup(database)
    assert _publish(database, principal, tenant_id, model_id, {'compaction_model_profile_version_id': str(model_id)})


def test_publish_rejects_a_compaction_model_outside_the_tenant(database):
    principal, tenant_id, model_id, foreign_id = _setup(database)
    with pytest.raises(NotFound):  # authorize_model reports foreign versions as unavailable
        _publish(database, principal, tenant_id, model_id, {'compaction_model_profile_version_id': str(foreign_id)})
