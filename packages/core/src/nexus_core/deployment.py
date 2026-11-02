"""Deployment configuration: the single source for operator settings in ``configs/nexus.toml``.

Every process (API, worker, migrations) reads the same file relative to its working directory.
Environment variables and ``.env`` files are not read. Errors carry only the file name and a
generic reason, never parser details, secret values or raw values, so they are safe to display.
This module depends only on the standard library so that every package can use it.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


class DeploymentConfigError(RuntimeError):
    """A missing or invalid deployment setting, safe to display to an operator."""


#: Path of the deployment file relative to the working directory.
CONFIG_RELATIVE_PATH = Path("configs") / "nexus.toml"


def config_path() -> Path:
    """Return the deployment file path under the current working directory."""
    return Path.cwd() / CONFIG_RELATIVE_PATH


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Parse the deployment file; an absent file yields an empty mapping.

    Unreadable or malformed files raise DeploymentConfigError so that a typo cannot silently
    fall back to defaults. Parser details are intentionally not included in the message.
    """
    target = path or config_path()
    if not target.exists():
        return {}
    try:
        with target.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        raise DeploymentConfigError(f"Cannot read {CONFIG_RELATIVE_PATH.as_posix()}: check file access and TOML syntax") from None


def section(name: str, path: Path | None = None) -> dict[str, Any]:
    """Return the table ``[name]``; an absent table yields an empty mapping.

    A key that is present but not a table raises DeploymentConfigError.
    """
    value = load_config(path).get(name, {})
    if not isinstance(value, dict):
        raise DeploymentConfigError(f"{CONFIG_RELATIVE_PATH.as_posix()} [{name}] must be a table")
    return value
