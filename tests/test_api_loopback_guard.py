"""Development mode is reachable only on loopback addresses (proposal 2026-11-04-skill-scripts, task 1.4)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import nexus_api.security as security
from nexus_api.main import app
from nexus_platform.configuration import DatabaseConfigurationError


@pytest.mark.parametrize('host,expected', [
    ('127.0.0.1', True), ('127.10.0.2', True), ('::1', True), ('localhost', True), ('::ffff:127.0.0.1', True),
    ('0.0.0.0', False), ('192.168.1.10', False), ('10.0.0.5', False), ('::', False), (None, False), ('', False),
    ('example.com', False),
])
def test_loopback_addresses(host, expected):
    assert security.is_loopback(host) is expected


def _mode(monkeypatch, mode):
    monkeypatch.setattr(security, 'auth_settings', lambda *a, **k: SimpleNamespace(mode=mode))


def test_development_mode_refuses_non_loopback_connections(monkeypatch):
    _mode(monkeypatch, 'development')
    response = TestClient(app, base_url='http://192.168.1.10:8000').get('/docs')
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'forbidden'


def test_development_mode_accepts_loopback_connections(monkeypatch):
    _mode(monkeypatch, 'development')
    assert TestClient(app, base_url='http://127.0.0.1:8000').get('/docs').status_code == 200


def test_other_modes_are_not_restricted_by_the_guard(monkeypatch):
    _mode(monkeypatch, 'session')
    assert TestClient(app, base_url='http://192.168.1.10:8000').get('/docs').status_code == 200


def test_unreadable_configuration_does_not_block_the_guard_itself(monkeypatch):
    def broken(*a, **k):
        raise DatabaseConfigurationError('bad file')
    monkeypatch.setattr(security, 'auth_settings', broken)
    assert TestClient(app, base_url='http://192.168.1.10:8000').get('/docs').status_code == 200
