"""Agent editor backend (openspec 2026-11-05-weknora-agent-tool-model-settings).

Covers the builtin tool catalog, agent-level generation settings, archiving and copying.
"""
import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole
from nexus_platform.agents.generation import merged_model_options, validate_context_window_budget, validate_generation
from nexus_platform.errors import Conflict
from nexus_platform.persistence.models import AuditRecord
from nexus_platform.runs.service import claim_next, create_run
from nexus_platform.sessions.service import create_session
from nexus_platform.tenants.service import add_member
from test_platform import create_agent_stack, database  # noqa: F401  (fixture)

OWNER = Principal(id="editor-owner", issuer="test")
MEMBER = Principal(id="editor-member", issuer="test")
STRANGER = Principal(id="editor-stranger", issuer="test")


@pytest.fixture
def api(database):
    """A TestClient whose principal can be switched with ``api.as_(principal)``."""
    app.state.session_factory = database
    current = {"principal": OWNER}

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: current["principal"]
    with TestClient(app) as client:
        client.as_ = lambda principal: current.__setitem__("principal", principal)
        yield client
    app.dependency_overrides.clear()
    app.state.session_factory = None


def _stack(database):
    tenant, _, model_version, agent, version, session = create_agent_stack(database, OWNER)
    with database() as db:  # builtin tools live in the system space, which the API registers at startup
        from nexus_platform.system import ensure_system_resources
        ensure_system_resources(db)
    with database() as db:
        add_member(db, OWNER, tenant.id, MEMBER, TenantRole.CONTRIBUTOR)
    return tenant.id, model_version, agent, version, session


def _draft(model_version, **extra):
    return {"name": "Editor agent", "runtime_type": "native", "instructions": "Be precise",
            "model_profile_version_id": str(model_version.id), **extra}


# ---- generation settings -----------------------------------------------------------------------

def test_generation_validation_rejects_unknown_keys_and_ranges():
    validate_generation({})
    validate_generation({"generation": {"temperature": 0.7, "reasoning_effort": "high"}})
    for bad in ({"temperature": 2.5}, {"temperature": True}, {"reasoning_effort": "turbo"}, {"top_k": 3}):
        with pytest.raises(ValueError):
            validate_generation({"generation": bad})
    with pytest.raises(ValueError):
        validate_generation({"generation": []})


def test_agent_generation_overrides_model_options():
    profile = {"temperature": 0.2, "reasoning_effort": "low", "stream": True}
    assert merged_model_options(profile, {}) == profile
    assert merged_model_options(profile, {"generation": {"temperature": 0.9}}) == {**profile, "temperature": 0.9}
    assert merged_model_options(profile, {"generation": {"reasoning_effort": "auto"}}) == profile
    assert "reasoning_effort" not in merged_model_options(profile, {"generation": {"reasoning_effort": "off"}})
    assert merged_model_options(profile, {"generation": {"reasoning_effort": "high"}})["reasoning_effort"] == "high"


def test_agent_context_window_budget_uses_k_tokens_and_zero_follows_model():
    validate_context_window_budget({})
    validate_context_window_budget({'context_window_k': 0})
    validate_context_window_budget({'context_window_k': 128})
    for value in (-1, 2001, True, 128.0):
        with pytest.raises(ValueError):
            validate_context_window_budget({'context_window_k': value})


def test_agent_api_rejects_invalid_generation_with_422(api, database):
    tid, model_version, *_ = _stack(database)
    bad = api.post(f"/api/v1/tenants/{tid}/agents",
                   json=_draft(model_version, budgets={"generation": {"temperature": 9}}))
    assert bad.status_code == 422, bad.text
    good = api.post(f"/api/v1/tenants/{tid}/agents",
                    json=_draft(model_version, budgets={"generation": {"temperature": 0.5}}))
    assert good.status_code == 201, good.text
    assert good.json()["budgets"]["generation"] == {"temperature": 0.5}


def test_preparation_passes_agent_generation_to_model(database):
    """The worker context carries profile options merged with the published agent's generation."""
    from nexus_platform.agents.service import publish_agent, update_agent_draft
    from nexus_platform.runs.preparation import prepare_execution
    tid, model_version, agent, _, _ = _stack(database)
    with database() as db:
        update_agent_draft(db, OWNER, tid, agent.id, name=agent.name, description="", runtime_type="native",
                           instructions="x", model_profile_version_id=model_version.id,
                           budgets={"generation": {"temperature": 1.3}}, bindings=[])
    with database() as db:
        version = publish_agent(db, OWNER, tid, agent.id)
    with database() as db:
        session = create_session(db, OWNER, tid, agent_version_id=version.id)
    with database() as db:
        create_run(db, OWNER, tid, session.id, message="hi", idempotency_key="gen-1")
    with database() as db:
        task = claim_next(db, "worker-test")
    context = prepare_execution(database, task, "worker-test")
    assert context is not None
    assert context.options["temperature"] == 1.3


# ---- tool catalog ------------------------------------------------------------------------------

def test_tool_catalog_lists_builtins_with_enablement(api, database):
    tid, *_ = _stack(database)
    listed = api.get(f"/api/v1/tenants/{tid}/agent-tools")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    names = [tool["name"] for tool in body["tools"]]
    assert "todo" in names and "ask_user" in names
    todo = next(tool for tool in body["tools"] if tool["name"] == "todo")
    # Builtin tools are assignable in every space without an enable step.
    assert todo["group"] == "base" and todo["enabled_in_tenant"] is True and todo["builtin"] is True
    assert todo["disabled"] is False
    assert body["can_enable_tools"] is True and body["groups"][0] == "base"
    # The space may switch one off for itself; the old enable call lifts that again.
    assert api.put(f"/api/v1/tenants/{tid}/builtin-disabled/tool/todo").status_code == 200
    todo = next(t for t in api.get(f"/api/v1/tenants/{tid}/agent-tools").json()["tools"] if t["name"] == "todo")
    assert todo["enabled_in_tenant"] is False and todo["disabled"] is True
    assert api.post(f"/api/v1/tenants/{tid}/tools/todo/enable").status_code == 201
    todo = next(t for t in api.get(f"/api/v1/tenants/{tid}/agent-tools").json()["tools"] if t["name"] == "todo")
    assert todo["enabled_in_tenant"] is True and todo["disabled"] is False

    api.as_(MEMBER)
    member_view = api.get(f"/api/v1/tenants/{tid}/agent-tools")
    assert member_view.status_code == 200 and member_view.json()["can_enable_tools"] is False
    api.as_(STRANGER)
    assert api.get(f"/api/v1/tenants/{tid}/agent-tools").status_code == 404


# ---- archive and copy --------------------------------------------------------------------------

def test_archive_hides_agent_and_blocks_new_sessions_and_runs(api, database):
    tid, _, agent, version, session = _stack(database)
    api.as_(MEMBER)
    assert api.delete(f"/api/v1/tenants/{tid}/agents/{agent.id}").status_code in (403, 404)
    api.as_(OWNER)
    archived = api.delete(f"/api/v1/tenants/{tid}/agents/{agent.id}")
    assert archived.status_code == 204, archived.text
    assert api.get(f"/api/v1/tenants/{tid}/agents/{agent.id}").status_code == 404
    assert all(row["id"] != str(agent.id) for row in api.get(f"/api/v1/tenants/{tid}/agents").json())
    assert api.delete(f"/api/v1/tenants/{tid}/agents/{agent.id}").status_code == 404
    with database() as db:
        with pytest.raises(Conflict):
            create_session(db, OWNER, tid, agent_version_id=version.id)
    with database() as db:
        with pytest.raises(Conflict):
            create_run(db, OWNER, tid, session.id, message="after", idempotency_key="archived-1")
    history = api.get(f"/api/v1/tenants/{tid}/sessions/{session.id}/messages")
    assert history.status_code == 200, history.text
    with database() as db:
        actions = {row.action for row in db.query(AuditRecord).filter(AuditRecord.tenant_id == tid)}
    assert "agent.archived" in actions


def test_copy_creates_unpublished_draft_with_bindings(api, database):
    tid, model_version, agent, *_ = _stack(database)
    assert api.post(f"/api/v1/tenants/{tid}/tools/todo/enable").status_code == 201
    binding = {"kind": "tool", "resource_id": "todo", "resource_version_id": "v1"}
    updated = api.put(f"/api/v1/tenants/{tid}/agents/{agent.id}",
                      json=_draft(model_version, budgets={"generation": {"temperature": 0.4}},
                                  resource_bindings=[binding]))
    assert updated.status_code == 200, updated.text
    copied = api.post(f"/api/v1/tenants/{tid}/agents/{agent.id}/copy", json={})
    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert body["id"] != str(agent.id) and body["name"].endswith("(copy)")
    assert body["published_version_id"] is None and body["status"] == "draft"
    assert body["budgets"]["generation"] == {"temperature": 0.4}
    assert [row["resource_id"] for row in body["resource_bindings"]] == ["todo"]
    named = api.post(f"/api/v1/tenants/{tid}/agents/{agent.id}/copy", json={"name": "Second"})
    assert named.status_code == 201 and named.json()["name"] == "Second"
    api.as_(STRANGER)
    assert api.post(f"/api/v1/tenants/{tid}/agents/{agent.id}/copy", json={}).status_code == 404


def test_sandbox_policy_allows_enterprise_owner_and_denies_members(api, database, tmp_path, monkeypatch):
    tenant_id, _, _, _, _ = _stack(database)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs' / 'nexus.toml').write_text(f'''
[sandbox]
enabled = true
workspace_root = "{tmp_path / 'shared'}"
[sandbox.profiles.remote]
type = "managed"
endpoint = "https://sandbox.example.test"
token_file = "/run/secrets/hidden"
remote_profile = "node"
''')
    url = f'/api/v1/tenants/{tenant_id}/admin/sandboxes/remote'
    policy = {'paused': True, 'exec_timeout_max_seconds': 60, 'skill_timeout_seconds': 30,
              'skill_timeout_max_seconds': 90}
    detail = api.get(url)
    assert detail.status_code == 200
    assert detail.json()['editable']
    assert detail.json()['configuration']['token_file'] == '/run/secrets/hidden'
    assert api.put(f'{url}/policy', json=policy).status_code == 200
    api.as_(MEMBER)
    assert api.get(url).status_code == 403
    assert api.put(f'{url}/policy', json=policy).status_code == 403
    assert api.post(f'{url}/connect').status_code == 403
    assert api.get(f'{url}/provider').status_code == 403
    assert api.put(f'{url}/provider', json={
        'type': 'e2b', 'template': 'base', 'domain': 'e2b.app', 'revision': 'v1',
    }).status_code == 403
    assert api.get(f'{url}/executions').status_code == 403
    assert api.post(f'{url}/executions/{"a" * 32}/cleanup').status_code == 403
    api.as_(STRANGER)
    assert api.get(url).status_code in (403, 404)
    api.as_(OWNER)
    result = api.put(f'{url}/policy', json=policy)
    assert result.status_code == 200 and result.json()['policy'] == policy
    assert result.json()['reason'] == 'sandbox_profile_paused'
    assert api.get(url).json()['policy'] == policy


def test_gateway_connection_and_provider_changes_invalidate_old_acceptance(api, database, tmp_path, monkeypatch):
    import httpx
    from nexus_sandbox.settings import load_config

    tenant_id, _, _, _, _ = _stack(database)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir()
    key = tmp_path / 'gateway-key'
    key.write_text('gateway-access-token')
    (tmp_path / 'configs' / 'nexus.toml').write_text(f'''
[sandbox]
enabled = true
workspace_root = "{tmp_path / 'shared'}"
[sandbox.profiles.remote]
type = "managed"
endpoint = "https://sandbox.example.test"
token_file = "{key}"
remote_profile = "node"
''')
    capabilities = {
        'policy_digest': 'a' * 64, 'provider': 'e2b', 'file_transfer': 'snapshot',
        'network': 'none', 'output_capture': 'bounded', 'cleanup': 'persistent',
        'background': False, 'build': False, 'template_revision': 'v1',
    }
    writes = []
    def transport(request):
        assert request.headers['authorization'] == 'Bearer gateway-access-token'
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200, json=capabilities)
        if request.url.path.endswith('/provider'):
            if request.method == 'PUT':
                writes.append(request.content)
            return httpx.Response(200, json={
                'type': 'e2b', 'template': 'base', 'domain': 'e2b.app', 'revision': 'v2', 'has_api_key': True,
            })
        return httpx.Response(404)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    url = f'/api/v1/tenants/{tenant_id}/admin/sandboxes/remote'
    connected = api.post(f'{url}/connect')
    assert connected.status_code == 200
    assert connected.json()['connection']['policy_digest'] == 'a' * 64
    assert load_config().get('remote').remote_policy_digest == 'a' * 64
    response = api.put(f'{url}/provider', json={
        'type': 'e2b', 'template': 'base', 'domain': 'e2b.app', 'revision': 'v2', 'api_key': 'supplier-secret',
    })
    assert response.status_code == 200 and 'supplier-secret' not in response.text and writes
    assert load_config().get('remote').remote_policy_digest == ''
    assert api.get(url).json()['reason'] == 'sandbox_connection_required'


@pytest.mark.parametrize("role", [TenantRole.OWNER, TenantRole.ADMIN])
def test_sandbox_configuration_crud_permissions_revision_and_live_catalog(api, database, tmp_path, monkeypatch, role):
    from nexus_sandbox.settings import load_config

    tenant_id, _, _, _, _ = _stack(database)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs' / 'nexus.toml').write_text(f'''
[sandbox]
enabled = true
workspace_root = "{tmp_path / 'shared'}"
[sandbox.profiles.local]
type = "local"
''')
    root = f'/api/v1/tenants/{tenant_id}/admin/sandboxes'
    listing = api.get(root)
    assert listing.status_code == 200 and listing.json()['can_manage']
    values = {'type': 'docker', 'display_name': '研发隔离环境', 'image': 'python:3.12-slim'}
    api.as_(MEMBER)
    assert api.post(root, json={'revision': 0, 'values': values}).status_code == 403
    assert api.get(root).status_code == 403
    assert api.put(f'{root}/local/configuration', json={'revision': 0, 'values': {'type': 'local'}}).status_code == 403
    assert api.delete(f'{root}/local?revision=0').status_code == 403
    if role == TenantRole.ADMIN:
        administrator = Principal(id='sandbox-admin', issuer='test')
        with database() as db:
            add_member(db, OWNER, tenant_id, administrator, role)
        api.as_(administrator)
    else:
        api.as_(OWNER)
    created = api.post(root, json={'revision': 0, 'values': values})
    assert created.status_code == 201, created.text
    name = created.json()['name']
    assert name.startswith('sandbox_') and created.json()['display_name'] == '研发隔离环境'
    assert load_config().get(name).image == 'python:3.12-slim'
    assert api.post(root, json={'revision': 0, 'values': values}).status_code == 409
    edited = api.put(f'{root}/{name}/configuration', json={'revision': 1, 'values': values | {'memory_mb': 1024}})
    assert edited.status_code == 200
    assert load_config().get(name).memory_mb == 1024
    assert edited.json()['revision'] == 2
    catalog = api.get(f'/api/v1/tenants/{tenant_id}/agent-tools').json()
    assert any(item['name'] == name and item['display_name'] == '研发隔离环境' for item in catalog['sandbox_profiles'])
    assert api.delete(f'{root}/{name}?revision=1').status_code == 409
    assert api.delete(f'{root}/{name}?revision=2').status_code == 204
    assert load_config().get(name) is None
    assert api.get(f'{root}/{name}').status_code == 404
    assert api.delete(f'{root}/local?revision=3').status_code == 409


def test_sandbox_configuration_preserves_published_references_and_invalidates_runtime_policy(api, database, tmp_path, monkeypatch):
    from nexus_platform.identity.service import resolve_user
    from nexus_platform.persistence.models import AgentRecord, AgentVersionRecord
    from nexus_sandbox.settings import load_config, save_profile_policy
    tenant_id, _, agent, version, _ = _stack(database)
    with database() as db, db.begin():
        resolve_user(db, OWNER).is_platform_admin = True
        db.get(AgentRecord, agent.id).draft_budgets = {'behavior': {'sandbox_profile': 'docker'}}
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs' / 'nexus.toml').write_text(f'''
[sandbox]
enabled = true
default_profile = "local"
workspace_root = "{tmp_path / 'shared'}"
[sandbox.profiles.local]
type = "local"
[sandbox.profiles.docker]
type = "docker"
''')
    root = f'/api/v1/tenants/{tenant_id}/admin/sandboxes'
    save_profile_policy(load_config().get('docker'), {'exec_timeout_max_seconds': 30, 'paused': True})
    invalid = api.put(f'{root}/docker/configuration', json={
        'revision': 0, 'values': {'type': 'docker', 'cpus': 0, 'display_name': 'Bad'},
    })
    assert invalid.status_code == 422
    changed = api.put(f'{root}/docker/configuration', json={
        'revision': 0, 'values': {'type': 'docker', 'display_name': 'Updated', 'exec_timeout_max_seconds': 60},
    })
    assert changed.status_code == 200, changed.text
    settings = load_config().get('docker')
    assert settings.exec_timeout_max_seconds == 60 and settings.paused
    assert api.delete(f'{root}/docker?revision=1').status_code == 409

    with database() as db, db.begin():
        db.get(AgentRecord, agent.id).draft_budgets = {}
        db.get(AgentVersionRecord, version.id).budgets = {'behavior': {'sandbox_profile': 'docker'}}
    assert api.delete(f'{root}/docker?revision=1').status_code == 409
    assert api.put(f'{root}/docker/configuration', json={
        'revision': 1, 'values': {'type': 'local', 'display_name': 'Changed backend'},
    }).status_code == 409


@pytest.mark.parametrize('kind', ['docker', 'local', 'bwrap', 'ssh', 'managed'])
def test_sandbox_editor_defaults_save_and_reload_through_real_api(api, database, tmp_path, monkeypatch, kind):
    """Exercise the complete editor payload, including hidden defaults, against actual persistence."""
    from nexus_sandbox.settings import load_config

    tenant_id, *_ = _stack(database)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir()
    root = tmp_path / 'shared'
    (tmp_path / 'configs' / 'nexus.toml').write_text(f'[sandbox]\nworkspace_root = "{root}"\n')
    url = f'/api/v1/tenants/{tenant_id}/admin/sandboxes'
    catalog = api.get(url).json()
    values = catalog['defaults'][kind] | {'display_name': f'新增 {kind}', 'description': '真实参数回归'}
    if kind == 'ssh':
        values.update(ssh_host='node.example.test', ssh_user='nexus', ssh_identity_file='/run/key',
                      ssh_known_hosts='/run/hosts', remote_profile='bwrap')
    elif kind == 'managed':
        values.update(endpoint='https://node.example.test', token_file='/run/token', remote_profile='docker')
    created = api.post(url, json={'revision': catalog['revision'], 'values': values})
    assert created.status_code == 201, created.text
    name = created.json()['name']
    assert load_config().get(name).display_name == f'新增 {kind}'
    assert (root / '_sandbox_profiles.json').is_file()
    fresh = api.get(url).json()
    record = next(item for item in fresh['items'] if item['name'] == name)
    assert record['configuration'] == created.json()['configuration']
    changed = api.put(f'{url}/{name}/configuration', json={
        'revision': fresh['revision'], 'values': record['configuration'] | {'display_name': '再次保存'},
    })
    assert changed.status_code == 200, changed.text
    assert load_config().get(name).display_name == '再次保存'
    assert '再次保存' in (root / '_sandbox_profiles.json').read_text()
