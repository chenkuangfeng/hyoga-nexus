"""Agent editor backend (openspec 2026-11-05-weknora-agent-tool-model-settings).

Covers the builtin tool catalog, agent-level generation settings, archiving and copying.
"""
import pytest
from fastapi.testclient import TestClient

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole
from nexus_platform.agents.generation import merged_model_options, validate_generation
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
