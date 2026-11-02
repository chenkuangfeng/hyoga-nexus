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
