"""Development mode signs in as one existing local account; the web client gets a real session for it.

The account is `[auth].dev_user_id` (a username, default owner `9600543` after bootstrap). Accounts are never
created in development mode, and `/auth/dev-session` exists only in development mode.
"""
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from nexus_api.dependencies.platform import get_principal
from nexus_api.main import app
from nexus_platform.bootstrap import DEFAULT_OWNER_USERNAME, ensure_default_enterprise
from nexus_platform.persistence.models import Base

LOOPBACK_URL = "http://127.0.0.1:8000"  # the guard checks the listening address (scope server)


@pytest.fixture
def factory(deployment_config) -> Iterator[sessionmaker]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    fac = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with fac() as db:
        ensure_default_enterprise(db)
    previous = getattr(app.state, "session_factory", None)
    app.state.session_factory = fac
    yield fac
    app.state.session_factory = previous
    engine.dispose()


def _request() -> Request:
    scope = {'type': 'http', 'method': 'GET', 'path': '/', 'headers': [], 'query_string': b'', 'app': FastAPI()}
    return Request(scope)


def _dev_mode(deployment_config, dev_user_id: str | None = None) -> None:
    line = f'dev_user_id = "{dev_user_id}"\n' if dev_user_id is not None else ""
    deployment_config(f'[auth]\nmode = "development"\n{line}')


def test_development_principal_is_the_configured_existing_account(deployment_config, factory):
    _dev_mode(deployment_config, DEFAULT_OWNER_USERNAME)
    with factory() as db:
        principal = get_principal(_request(), db=db)
    assert principal.id == DEFAULT_OWNER_USERNAME
    assert principal.issuer == "password"


def test_development_mode_never_creates_an_account(deployment_config, factory):
    _dev_mode(deployment_config, "nobody")
    with factory() as db:
        with pytest.raises(HTTPException) as caught:
            get_principal(_request(), db=db)
    assert caught.value.status_code == 503
    assert "nobody" in caught.value.detail


def test_dev_session_issues_a_working_session_for_the_owner(deployment_config, factory):
    _dev_mode(deployment_config, DEFAULT_OWNER_USERNAME)
    client = TestClient(app, base_url=LOOPBACK_URL)
    body = client.post("/api/v1/auth/dev-session").json()
    assert body["success"] is True and body["token"]
    assert body["user"]["username"] == DEFAULT_OWNER_USERNAME
    assert body["active_tenant"]["name"] == "hyoga"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200, me.text


def test_dev_session_is_not_available_in_session_mode(deployment_config, factory):
    deployment_config('[auth]\nmode = "session"\n')
    response = TestClient(app, base_url=LOOPBACK_URL).post("/api/v1/auth/dev-session")
    assert response.status_code == 404


def test_auth_config_advertises_development_login(deployment_config, factory):
    _dev_mode(deployment_config, DEFAULT_OWNER_USERNAME)
    assert TestClient(app, base_url=LOOPBACK_URL).get("/api/v1/auth/config").json()["development_login"] is True
