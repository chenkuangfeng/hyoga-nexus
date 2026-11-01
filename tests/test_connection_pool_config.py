"""Configurable provider connection pool: validated settings, applied to pools created by the worker."""
import asyncio

import pytest

from nexus_platform.configuration import DatabaseConfigurationError, ConnectionPoolSettings, model_connection_pool
from nexus_runtimes.native.models import network


def _write(tmp_path, body):
    (tmp_path / 'configs').mkdir(exist_ok=True)
    path = tmp_path / 'configs' / 'nexus.toml'
    path.write_text(body)
    return path


def test_absent_section_means_httpx_defaults(tmp_path):
    assert model_connection_pool(tmp_path / 'missing.toml') == ConnectionPoolSettings(100, 20, 5.0)
    assert model_connection_pool(_write(tmp_path, '[database]\nurl = "sqlite:///x"\n')) == ConnectionPoolSettings(100, 20, 5.0)


def test_explicit_values_are_read(tmp_path):
    path = _write(tmp_path, '[model_connection_pool]\nmax_connections = 16\nmax_keepalive_connections = 4\nkeepalive_expiry_seconds = 30\n')
    assert model_connection_pool(path) == ConnectionPoolSettings(16, 4, 30.0)


@pytest.mark.parametrize('body', [
    'max_connections = 0',
    'max_connections = "10"',
    'max_connections = true',
    'max_keepalive_connections = -1',
    'max_connections = 4\nmax_keepalive_connections = 5',
    'keepalive_expiry_seconds = 0',
    'keepalive_expiry_seconds = 301',
    'keepalive_expiry_seconds = "5"',
])
def test_invalid_values_fail_closed(tmp_path, body):
    with pytest.raises(DatabaseConfigurationError):
        model_connection_pool(_write(tmp_path, '[model_connection_pool]\n' + body + '\n'))


def test_non_table_section_fails_closed(tmp_path):
    with pytest.raises(DatabaseConfigurationError):
        model_connection_pool(_write(tmp_path, 'model_connection_pool = 3\n'))


def test_configured_limits_apply_to_pools_created_afterwards(monkeypatch):
    monkeypatch.setenv('NEXUS_MODEL_PRIVATE_HOST_ALLOWLIST', '127.0.0.1')
    monkeypatch.setattr(network, '_POOLS', {})
    monkeypatch.setattr(network, '_POOL_LIMITS', network._POOL_LIMITS)
    network.configure_connection_pool(max_connections=7, max_keepalive_connections=3, keepalive_expiry=2.5)
    async def main():
        return network.shared_connection_pool('http://127.0.0.1:19001/v1')
    pool = asyncio.run(main())
    assert (pool._pool._max_connections, pool._pool._max_keepalive_connections, pool._pool._keepalive_expiry) == (7, 3, 2.5)
