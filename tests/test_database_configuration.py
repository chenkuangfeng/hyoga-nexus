"""Deployment config precedence, redaction and entrypoint integration."""
from pathlib import Path
import subprocess
import sys

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest

from nexus_platform.configuration import DatabaseConfigurationError, resolve_database_url
from nexus_platform.persistence.database import create_database_engine


@pytest.fixture
def deployment(deployment_config):
    """Empty deployment directory; the test writes configs/nexus.toml through the returned path."""
    return deployment_config()


def test_sources_and_explicit_injection(deployment, monkeypatch):
    # Missing file, missing section and missing key are all errors: there is no environment fallback.
    with pytest.raises(DatabaseConfigurationError, match='configs/nexus.toml'):
        resolve_database_url()
    deployment.write_text('[other]\nvalue = true\n')
    with pytest.raises(DatabaseConfigurationError, match='configs/nexus.toml'):
        resolve_database_url()
    deployment.write_text('[database]\n')
    with pytest.raises(DatabaseConfigurationError, match='configs/nexus.toml'):
        resolve_database_url()
    deployment.write_text('[database]\nurl = "sqlite:///file.db"\n')
    assert resolve_database_url() == 'sqlite:///file.db'
    assert resolve_database_url('sqlite:///explicit.db') == 'sqlite:///explicit.db'
    engine = create_database_engine('sqlite://')
    assert engine.url.database is None
    engine.dispose()
    # Neither environment variables nor a .env file are read.
    monkeypatch.setenv('NEXUS_DATABASE_URL', 'sqlite:///environment.db')
    deployment.unlink()
    Path('.env').write_text('NEXUS_DATABASE_URL=sqlite:///dotenv.db\n')
    with pytest.raises(DatabaseConfigurationError):
        resolve_database_url()


@pytest.mark.parametrize('content', [
    '[database\nurl = "secret-password"',
    'database = "secret-password"',
    '[database]\nurl = 123',
    '[database]\nurl = ""',
    '[database]\nurl = "   "',
    '[database]\nurl = "secret-password"',
    '[database]\nurl = "postgresql://user:secret-password@localhost:bad/db"',
])
def test_invalid_file_does_not_fall_back_or_expose_values(deployment, content):
    deployment.write_text(content)
    with pytest.raises(DatabaseConfigurationError) as error:
        resolve_database_url()
    assert 'secret-password' not in str(error.value)
    assert error.value.__suppress_context__ or error.value.__context__ is None


def test_api_worker_and_migration_share_file(deployment, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    deployment.write_text('[database]\nurl = "sqlite:///smoke.db"\n')
    # Alembic locates migration scripts from its absolute ini path, config from cwd.
    config = Config(str(root / 'alembic.ini'))
    command.upgrade(config, 'head')
    assert Path('smoke.db').exists()
    from nexus_api.main import app
    monkeypatch.delattr(app.state, 'database_engine', raising=False)
    monkeypatch.delattr(app.state, 'session_factory', raising=False)
    try:
        with TestClient(app) as client:
            assert client.get('/api/v1/ready').json()['status'] == 'ready'
    finally:
        engine = app.state.database_engine
        engine.dispose()
        monkeypatch.delattr(app.state, 'database_engine')
        monkeypatch.delattr(app.state, 'session_factory')
    result = subprocess.run([sys.executable, '-m', 'nexus_worker', '--once'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'Worker started' in result.stderr
    assert 'Worker task failed' not in result.stderr


def test_api_and_worker_missing_configuration(deployment, monkeypatch):
    from nexus_api.main import app
    monkeypatch.delattr(app.state, 'database_engine', raising=False)
    monkeypatch.delattr(app.state, 'session_factory', raising=False)
    with TestClient(app) as client:
        assert client.get('/api/v1/health').status_code == 200
        response = client.get('/api/v1/ready')
        assert response.status_code == 503
        assert response.json()['reason'] == 'database_not_configured'
    result = subprocess.run([sys.executable, '-m', 'nexus_worker', '--once'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert 'configs/nexus.toml' in result.stderr
