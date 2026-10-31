from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from nexus_core.platform import Principal
from nexus_platform.agents.service import create_agent, publish_agent
from nexus_platform.models.service import create_model_profile
from nexus_platform.runs.service import claim_next, create_run
from nexus_platform.sessions.service import create_session
from nexus_platform.tenants.service import create_tenant


def test_postgres_migrations_concurrent_claim_and_lease_recovery(monkeypatch):
    database_url = os.getenv("NEXUS_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("Set NEXUS_TEST_POSTGRES_URL to a dedicated PostgreSQL test database")
    parsed = make_url(database_url)
    if not parsed.database or not re.search(r"(^|[_-])test($|[_-])", parsed.database, re.IGNORECASE):
        pytest.skip("PostgreSQL integration test requires a database name containing 'test'")

    schema = "nexus_test_" + uuid4().hex[:12]
    admin_engine = create_engine(database_url)
    admin_url = parsed.set(query={**parsed.query, "options": f"-csearch_path={schema}"})
    scoped_url = admin_url.render_as_string(hide_password=False)
    scoped_engine = create_engine(scoped_url, pool_size=5, max_overflow=5)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        monkeypatch.setenv("NEXUS_DATABASE_URL", scoped_url)
        config = Config("alembic.ini")
        config.attributes["database_url"] = scoped_url
        command.upgrade(config, "head")
        with scoped_engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current

        factory = sessionmaker(bind=scoped_engine, expire_on_commit=False, autoflush=False)
        principal = Principal(id="postgres-test-owner", issuer="integration-test")
        with factory() as session:
            tenant = create_tenant(session, principal, "PostgreSQL integration")
            _, model_version = create_model_profile(
                session, principal, tenant.id, name="model", provider="test", model_name="test", options={}
            )
            agent = create_agent(
                session, principal, tenant.id, name="agent", description="", runtime_type="native",
                instructions="", model_profile_version_id=model_version.id, budgets={}, bindings=[],
            )
            version = publish_agent(session, principal, tenant.id, agent.id)
            platform_session = create_session(session, principal, tenant.id, agent_version_id=version.id)
            run, _ = create_run(
                session, principal, tenant.id, platform_session.id, message="first",
                idempotency_key="concurrent-claim",
            )

        def claim(worker_id):
            with factory() as session:
                return claim_next(session, worker_id, lease_seconds=1)

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim, ["worker-a", "worker-b"]))
        assert claims.count(None) == 1
        claimed_id = next(item for item in claims if item is not None)

        time.sleep(1.1)
        with factory() as session:
            reclaimed_id = claim_next(session, "worker-recovery", lease_seconds=1)
        assert reclaimed_id == claimed_id

        with factory() as session:
            second_session = create_session(session, principal, tenant.id, agent_version_id=version.id)
            second_run, _ = create_run(
                session, principal, tenant.id, second_session.id, message="second",
                idempotency_key="lease-recovery",
            )
        with factory() as session:
            # The first task still has a live recovery lease; the next worker gets the second Run.
            another_id = claim_next(session, "worker-c", lease_seconds=10)
        assert another_id is not None
        with factory() as session:
            from nexus_platform.persistence.models import OutboxRecord
            task = session.get(OutboxRecord, another_id)
            assert str(task.run_id) == str(second_run.id)
            assert str(run.id) != str(second_run.id)
    finally:
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
