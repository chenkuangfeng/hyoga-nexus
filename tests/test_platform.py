from __future__ import annotations

from collections.abc import Iterator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, RunStatus, TenantRole, new_id
from nexus_platform.agents.service import publish_agent, update_agent_draft
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.models.service import create_model_profile
from nexus_platform.persistence.models import AgentVersionRecord, Base, ResourceBindingRecord, RunRecord
from nexus_platform.runs.service import (
    authorize_run_resource,
    create_run,
    list_events,
    process_claimed,
    claim_next,
    request_cancel,
    transition_run,
)
from nexus_platform.tenants.service import create_tenant
from nexus_platform.authz.resources import grant_resource, register_resource, revoke_resource_grant
from nexus_platform.agents.service import create_agent
from nexus_platform.sessions.service import create_session


@pytest.fixture
def database() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    yield factory
    engine.dispose()


def create_agent_stack(factory, principal: Principal, *, name: str = "Research Agent", bindings=None):
    with factory() as db:
        tenant = create_tenant(db, principal, "Research")
        profile, model_version = create_model_profile(
            db, principal, tenant.id, name="Research Model", provider="openai",
            model_name="test-model", options={"base_url": "https://model.example/v1"},
        )
        agent = create_agent(
            db, principal, tenant.id, name=name, description="test", runtime_type="native",
            instructions="Use authorized resources only", model_profile_version_id=model_version.id,
            budgets={"max_rounds": 5}, bindings=bindings or [],
        )
        version = publish_agent(db, principal, tenant.id, agent.id)
        session = create_session(db, principal, tenant.id, agent_version_id=version.id, title="First")
    return tenant, profile, model_version, agent, version, session


def test_versioned_agent_session_run_idempotency_and_event_replay(database):
    principal = Principal(id="alice", issuer="test")
    tenant, profile, model_version, agent, first_version, session = create_agent_stack(database, principal)
    with database() as db:
        update_agent_draft(
            db, principal, tenant.id, agent.id, name="Research Agent", description="test",
            runtime_type="native", instructions="Revised instructions",
            model_profile_version_id=model_version.id, budgets={"max_rounds": 8}, bindings=[],
        )
    with database() as db:
        second_version = publish_agent(db, principal, tenant.id, agent.id)
        assert second_version.id != first_version.id
        assert second_version.version == first_version.version + 1
    with database() as db:
        assert db.get(AgentVersionRecord, first_version.id).instructions == "Use authorized resources only"
        assert db.get(type(session), session.id).agent_version_id == first_version.id
    with database() as db:
        first_run, replayed = create_run(
            db, principal, tenant.id, session.id, message="Analyze AAPL", idempotency_key="request-1"
        )
        assert replayed is False
    with database() as db:
        same_run, replayed = create_run(
            db, principal, tenant.id, session.id, message="Analyze AAPL", idempotency_key="request-1"
        )
        assert same_run.id == first_run.id
        assert replayed is True
    with database() as db:
        with pytest.raises(Conflict):
            create_run(
                db, principal, tenant.id, session.id, message="Analyze MSFT", idempotency_key="request-1"
            )
    with database() as db:
        assert "instructions" not in first_run.config_snapshot
        assert "credential_value" not in str(first_run.config_snapshot)
        task_id = claim_next(db, "worker-a")
        assert task_id is not None
    with database() as db:
        assert process_claimed(db, task_id, "worker-a") is True
    with database() as db:
        run = db.get(RunRecord, first_run.id)
        assert run.status == "failed"
        assert run.error_code == "runtime_not_configured"
    with database() as db:
        events = list_events(db, principal, tenant.id, run.id, after_sequence=0)
        assert [event.sequence for event in events] == [1, 2, 3]
        assert [event.event_type for event in events] == ["run.queued", "run.started", "run.failed"]
    with database() as db:
            replayed_events = list_events(db, principal, tenant.id, run.id, after_sequence=1)
            assert [event.sequence for event in replayed_events] == [2, 3]


def test_tenant_isolation_and_last_owner_protection(database):
    alice = Principal(id="alice", issuer="test")
    bob = Principal(id="bob", issuer="test")
    with database() as db:
        tenant = create_tenant(db, alice, "Alice space")
    with database() as db:
        with pytest.raises(NotFound):
            from nexus_platform.identity.service import require_membership
            with db.begin():
                bob_row = resolve_user(db, bob)
                require_membership(db, tenant.id, bob_row.id)
    with database() as db:
        with db.begin():
            owner = resolve_user(db, alice)
        owner_id = owner.id
    from nexus_platform.tenants.service import add_member, remove_member
    with database() as db:
        add_member(db, alice, tenant.id, bob, TenantRole.MEMBER)
    with database() as db:
        with pytest.raises(Forbidden):
            remove_member(db, bob, tenant.id, owner_id)
    with database() as db:
        with pytest.raises(Conflict):
            remove_member(db, alice, tenant.id, owner_id)


def test_resource_grant_is_rechecked_for_each_run_operation(database):
    principal = Principal(id="owner", issuer="test")
    with database() as db:
        source = create_tenant(db, principal, "Source")
        target = create_tenant(db, principal, "Target")
        with db.begin():
            register_resource(
                db, tenant_id=source.id, kind="knowledge_base", resource_id="kb-1", version_id="v1"
            )
        grant = grant_resource(
            db, principal, source_tenant_id=source.id, target_tenant_id=target.id,
            kind="knowledge_base", resource_id="kb-1", permissions=["use"],
        )
        _, model_version = create_model_profile(
            db, principal, target.id, name="Target model", provider="test", model_name="test", options={}
        )
        agent = create_agent(
            db, principal, target.id, name="Bound Agent", description="", runtime_type="native",
            instructions="", model_profile_version_id=model_version.id, budgets={},
            bindings=[{
                "kind": "knowledge_base", "resource_id": "kb-1", "resource_version_id": "v1",
                "source_tenant_id": str(source.id), "config": {},
            }],
        )
        version = publish_agent(db, principal, target.id, agent.id)
        session = create_session(db, principal, target.id, agent_version_id=version.id)
        run, _ = create_run(
            db, principal, target.id, session.id, message="Search", idempotency_key="resource-run"
        )
        with db.begin():
            row = db.get(RunRecord, run.id)
            row.status = "running"
        with db.begin():
            binding = db.scalar(
                select(ResourceBindingRecord).where(ResourceBindingRecord.agent_version_id == version.id)
            )
            binding_id = binding.id
        resource = authorize_run_resource(db, principal, target.id, run.id, binding_id)
        assert resource.resource_id == "kb-1"
        revoke_resource_grant(db, principal, grant.id)
        with pytest.raises(Forbidden):
            authorize_run_resource(db, principal, target.id, run.id, binding_id)


def test_platform_api_creates_tenant_and_rejects_secret_model_options(database):
    principal = Principal(id="api-user", issuer="test")
    app.state.session_factory = database

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/tenants", json={"name": "API tenant"})
            assert created.status_code == 201, created.text
            tenant_id = created.json()["id"]
            assert created.json()["role"] == "owner"
            profiles = client.post(
                f"/api/v1/tenants/{tenant_id}/model-profiles",
                json={"name": "Unsafe", "provider": "openai", "model_name": "x", "options": {"api_key": "dont-store"}},
            )
            assert profiles.status_code == 422
            listed = client.get("/api/v1/tenants")
            assert listed.status_code == 200
            assert len(listed.json()) == 1
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


def test_platform_api_publishes_agent_and_exposes_run_events(database):
    principal = Principal(id="workflow-user", issuer="test")
    current_principal = {"value": principal}
    app.state.session_factory = database

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: current_principal["value"]
    try:
        with TestClient(app) as client:
            tenant = client.post("/api/v1/tenants", json={"name": "Workflow"}).json()
            tenant_id = tenant["id"]
            profile_response = client.post(
                f"/api/v1/tenants/{tenant_id}/model-profiles",
                json={"name": "Model", "provider": "demo", "model_name": "demo-model", "options": {}},
            )
            assert profile_response.status_code == 201, profile_response.text
            model_version_id = profile_response.json()["current_version"]["id"]
            agent_response = client.post(
                f"/api/v1/tenants/{tenant_id}/agents",
                json={
                    "name": "Agent", "runtime_type": "native", "instructions": "Be precise",
                    "model_profile_version_id": model_version_id,
                },
            )
            assert agent_response.status_code == 201, agent_response.text
            agent_id = agent_response.json()["id"]
            version_response = client.post(
                f"/api/v1/tenants/{tenant_id}/agents/{agent_id}/publish"
            )
            assert version_response.status_code == 201, version_response.text
            published_version_id = version_response.json()["id"]
            session_response = client.post(
                f"/api/v1/tenants/{tenant_id}/sessions",
                json={"agent_version_id": version_response.json()["id"], "title": "Demo"},
            )
            assert session_response.status_code == 201, session_response.text
            run_response = client.post(
                f"/api/v1/tenants/{tenant_id}/sessions/{session_response.json()['id']}/runs",
                headers={"Idempotency-Key": "workflow-run"}, json={"message": "Hello"},
            )
            assert run_response.status_code == 202, run_response.text
            run_id = run_response.json()["id"]
            before = client.get(
                f"/api/v1/tenants/{tenant_id}/runs/{run_id}/events?after_sequence=0"
            )
            assert [event["sequence"] for event in before.json()] == [1]
            from nexus_worker.__main__ import run_once
            assert run_once(database, "api-test-worker") is True
            final_status = client.get(f"/api/v1/tenants/{tenant_id}/runs/{run_id}")
            assert final_status.json()["status"] == "failed"
            assert final_status.json()["error_code"] == "runtime_not_configured"
            after = client.get(
                f"/api/v1/tenants/{tenant_id}/runs/{run_id}/events?after_sequence=1"
            )
            assert [event["sequence"] for event in after.json()] == [2, 3]

            draft_response = client.post(
                f"/api/v1/tenants/{tenant_id}/agents",
                json={
                    "name": "Private draft", "runtime_type": "native", "instructions": "draft only",
                    "model_profile_version_id": model_version_id,
                },
            )
            assert draft_response.status_code == 201, draft_response.text
            member_response = client.post(
                f"/api/v1/tenants/{tenant_id}/members",
                json={"issuer": "test", "subject": "workflow-member", "role": "member"},
            )
            assert member_response.status_code == 201, member_response.text

            member_user_id = member_response.json()["user_id"]
            role = client.post(f"/api/v1/tenants/{tenant_id}/roles",
                               json={"name": "agent-viewer", "menus": ["agents"], "apis": ["agents:read"]})
            assert role.status_code == 201, role.text
            role_id = role.json()["id"]
            grant = client.put(f"/api/v1/tenants/{tenant_id}/roles/{role_id}/agents/{agent_id}",
                               json={"permissions": ["view", "run"]})
            assert grant.status_code == 200, grant.text
            assigned = client.put(f"/api/v1/tenants/{tenant_id}/members/{member_user_id}/roles/{role_id}")
            assert assigned.status_code == 204, assigned.text

            current_principal["value"] = Principal(id="workflow-member", issuer="test")
            visible_agents = client.get(f"/api/v1/tenants/{tenant_id}/agents")
            assert visible_agents.status_code == 200, visible_agents.text
            assert [row["name"] for row in visible_agents.json()] == ["Agent"]
            assert visible_agents.json()[0]["current_version"]["id"] == published_version_id
            profiles_for_member = client.get(f"/api/v1/tenants/{tenant_id}/model-profiles")
            assert profiles_for_member.status_code == 403
            owner_run_for_member = client.get(f"/api/v1/tenants/{tenant_id}/runs/{run_id}")
            assert owner_run_for_member.status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


def test_platform_api_does_not_default_to_a_development_identity(database, monkeypatch, tmp_path):
    # Run from an empty deployment directory so a developer's configs/nexus.toml [auth] cannot leak in.
    monkeypatch.chdir(tmp_path)
    app.state.session_factory = database

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/tenants")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "service_unavailable"
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None


def test_cancelled_queued_run_is_not_claimed_and_uuid_ids_are_v7(database):
    assert new_id().version == 7
    principal = Principal(id="cancel-user", issuer="test")
    tenant, _, _, _, _, platform_session = create_agent_stack(database, principal)
    with database() as db:
        run, _ = create_run(
            db, principal, tenant.id, platform_session.id, message="Cancel me", idempotency_key="cancel-run"
        )
    with database() as db:
        cancelled = request_cancel(db, principal, tenant.id, run.id)
        assert cancelled.status == "cancelled"
    with database() as db:
        assert claim_next(db, "worker-after-cancel") is None
        with pytest.raises(Conflict):
            transition_run(cancelled, RunStatus.RUNNING)
