"""Authentication settings from configs/nexus.toml [auth]; environment variables are not read."""
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from nexus_api.dependencies.platform import get_principal
from nexus_platform.configuration import AuthFileSettings, DatabaseConfigurationError, auth_settings


def _request():
    scope = {'type': 'http', 'method': 'GET', 'path': '/', 'headers': [], 'query_string': b'', 'app': FastAPI()}
    return Request(scope)


def test_absent_file_or_section_gives_defaults(deployment_config):
    deployment_config()
    assert auth_settings() == AuthFileSettings()  # cookies stay Secure
    deployment_config('[database]\nurl = "sqlite:///./nexus.db"\n')
    settings = auth_settings()
    assert settings.mode is None and settings.dev_user_id is None and settings.cookie_secure is True


def test_file_reads_mode_dev_user_and_cookie_flag(deployment_config):
    deployment_config('[auth]\nmode = " Development "\ndev_user_id = " alice "\ncookie_secure = false\n')
    settings = auth_settings()
    assert settings == AuthFileSettings(mode='development', dev_user_id='alice', cookie_secure=False)


@pytest.mark.parametrize('body', [
    '[auth]\nmode = "bogus"\n',
    '[auth]\nmode = 1\n',
    '[auth]\ndev_user_id = "   "\n',
    '[auth]\ndev_user_id = 3\n',
    '[auth]\ncookie_secure = "no"\n',
    'auth = "development"\n',
    '[auth\nmode = "development"\n',
])
def test_invalid_auth_section_is_rejected(deployment_config, body):
    deployment_config(body)
    with pytest.raises(DatabaseConfigurationError):
        auth_settings()


def _seeded_session(username: str):
    """A database with one password account named `username`; development mode must find it."""
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from nexus_platform.auth.accounts import PASSWORD_PROVIDER
    from nexus_platform.persistence.models import Base, UserIdentityRecord, UserRecord

    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with factory() as db, db.begin():
        user = UserRecord(id=uuid.uuid4(), status='active', email=f'{username}@example.com',
                          created_at=datetime.now(timezone.utc))
        db.add(user)
        db.flush()
        db.add(UserIdentityRecord(id=uuid.uuid4(), user_id=user.id, provider=PASSWORD_PROVIDER, scope='',
                                  external_id=username, created_at=datetime.now(timezone.utc)))
    return factory


def test_mode_comes_from_file(deployment_config):
    deployment_config('[auth]\nmode = "development"\ndev_user_id = "alice"\n')
    with _seeded_session('alice')() as db:
        assert get_principal(_request(), db=db).id == 'alice'


def test_environment_variables_are_ignored(deployment_config, monkeypatch):
    deployment_config('[auth]\nmode = "development"\ndev_user_id = "alice"\n')
    monkeypatch.setenv('NEXUS_AUTH_MODE', 'session')
    monkeypatch.setenv('NEXUS_DEV_USER_ID', 'bob')
    with _seeded_session('alice')() as db:
        assert get_principal(_request(), db=db).id == 'alice'


def test_unset_mode_is_unconfigured(deployment_config):
    deployment_config()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        get_principal(_request(), db=None)
    assert caught.value.status_code == 503
