"""Deployment database configuration shared by API, worker and migrations.

Paths are relative to the deployment working directory. No dotenv files are read,
and configuration errors intentionally omit parser details and secret values.
"""
from __future__ import annotations

import os
from pathlib import Path
import tomllib

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class DatabaseConfigurationError(RuntimeError):
    """A missing or invalid database setting, safe to display to an operator."""


def resolve_database_url(explicit_url: str | None = None) -> str:
    """Return explicit URL, configs/nexus.toml database.url, or legacy environment.

    Missing file/section permits environment fallback. Malformed files or declared
    invalid values fail closed. Raises DatabaseConfigurationError without secrets.
    No connections are opened and no process environment is modified.
    """
    source = "explicit database URL"
    value: object = explicit_url
    if explicit_url is None:
        path = Path.cwd() / "configs" / "nexus.toml"
        source = "configs/nexus.toml [database].url"
        try:
            with path.open('rb') as stream:
                data = tomllib.load(stream)
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError):
            raise DatabaseConfigurationError("Cannot read configs/nexus.toml: check file access and TOML syntax") from None
        if "database" in data:
            section = data["database"]
            if not isinstance(section, dict):
                raise DatabaseConfigurationError("configs/nexus.toml [database] must be a table")
            if "url" in section:
                value = section["url"]
            else:
                value = None
        if value is None and ("database" not in data or "url" not in data["database"]):
            source = "NEXUS_DATABASE_URL"
            value = os.environ.get("NEXUS_DATABASE_URL")
            if value is None:
                raise DatabaseConfigurationError("Configure configs/nexus.toml [database].url (or NEXUS_DATABASE_URL)")
    if not isinstance(value, str) or not value.strip():
        raise DatabaseConfigurationError(f"{source} must be a non-empty database URL string")
    try:
        parsed = make_url(value)
        # Force validation of numeric ports without displaying SQLAlchemy's input.
        _ = parsed.port
    except (ArgumentError, ValueError, TypeError):
        raise DatabaseConfigurationError(f"{source} is not a valid database URL") from None
    return value
