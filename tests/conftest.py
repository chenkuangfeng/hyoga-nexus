"""Shared pytest fixtures."""
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def deployment_config(tmp_path, monkeypatch) -> Callable[[str], Path]:
    """Run from an empty deployment directory and write its ``configs/nexus.toml``.

    The application reads every operator setting from this file, never from environment variables,
    so tests call the returned function with TOML text instead of setting environment variables.
    """
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "configs" / "nexus.toml"
    target.parent.mkdir()

    def write(text: str = "") -> Path:
        target.write_text(text, encoding="utf-8")
        return target

    return write


@pytest.fixture(autouse=True)
def no_leaked_dependency_overrides():
    """Fail the test that leaves FastAPI dependency overrides behind, not an unrelated one far later.

    A leaked ``get_principal`` override makes every later API test act as someone else. The usual cause is importing
    ``teardown_function`` inside a test body: pytest only runs one found at module level.
    """
    yield
    try:
        from nexus_api.main import app
    except ImportError:  # the API is not importable in this environment
        return
    leaked = sorted(getattr(key, "__name__", str(key)) for key in app.dependency_overrides)
    app.dependency_overrides.clear()
    assert not leaked, f"test left FastAPI dependency overrides behind: {leaked}"
