"""Deployment database configuration shared by API, worker and migrations.

Paths are relative to the deployment working directory. No dotenv files are read,
and configuration errors intentionally omit parser details and secret values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import tomllib

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class DatabaseConfigurationError(RuntimeError):
    """A missing or invalid database setting, safe to display to an operator."""


#: Default for ``[platform].max_concurrent_sessions``: sessions holding queued, started or unknown work.
DEFAULT_MAX_CONCURRENT_SESSIONS = 8


def max_concurrent_sessions(path: Path | None = None) -> int:
    """Return the global active-session cap from ``configs/nexus.toml [platform]``.

    Absent file or key yields the default. A malformed file or a non-positive integer raises
    DatabaseConfigurationError so that a typo cannot silently lift the cap.
    """
    target = path or Path.cwd() / "configs" / "nexus.toml"
    if not target.exists():
        return DEFAULT_MAX_CONCURRENT_SESSIONS
    try:
        with target.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        raise DatabaseConfigurationError("Cannot read configs/nexus.toml: check file access and TOML syntax") from None
    section = data.get("platform", {})
    if not isinstance(section, dict):
        raise DatabaseConfigurationError("configs/nexus.toml [platform] must be a table")
    value = section.get("max_concurrent_sessions", DEFAULT_MAX_CONCURRENT_SESSIONS)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DatabaseConfigurationError("configs/nexus.toml [platform].max_concurrent_sessions must be a positive integer")
    return value


#: Defaults match httpx's transport defaults, so an absent section changes nothing.
DEFAULT_POOL_MAX_CONNECTIONS = 100
DEFAULT_POOL_MAX_KEEPALIVE = 20
DEFAULT_POOL_KEEPALIVE_EXPIRY = 5.0
MAX_POOL_KEEPALIVE_EXPIRY = 300.0


@dataclass(frozen=True)
class ConnectionPoolSettings:
    """Limits for the per-origin provider connection pool used by worker Native Runs."""
    max_connections: int = DEFAULT_POOL_MAX_CONNECTIONS
    max_keepalive_connections: int = DEFAULT_POOL_MAX_KEEPALIVE
    keepalive_expiry_seconds: float = DEFAULT_POOL_KEEPALIVE_EXPIRY


def model_connection_pool(path: Path | None = None) -> ConnectionPoolSettings:
    """Read ``configs/nexus.toml [model_connection_pool]``; absent file or keys mean defaults.

    Invalid values raise DatabaseConfigurationError so that a typo cannot silently change pooling.
    Keep-alive connections may not exceed the total connection limit.
    """
    target = path or Path.cwd() / "configs" / "nexus.toml"
    if not target.exists():
        return ConnectionPoolSettings()
    try:
        with target.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        raise DatabaseConfigurationError("Cannot read configs/nexus.toml: check file access and TOML syntax") from None
    section = data.get("model_connection_pool", {})
    if not isinstance(section, dict):
        raise DatabaseConfigurationError("configs/nexus.toml [model_connection_pool] must be a table")

    def integer(key: str, default: int, minimum: int) -> int:
        value = section.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise DatabaseConfigurationError(f"configs/nexus.toml [model_connection_pool].{key} must be an integer >= {minimum}")
        return value

    max_connections = integer("max_connections", DEFAULT_POOL_MAX_CONNECTIONS, 1)
    max_keepalive = integer("max_keepalive_connections", DEFAULT_POOL_MAX_KEEPALIVE, 0)
    if max_keepalive > max_connections:
        raise DatabaseConfigurationError("configs/nexus.toml [model_connection_pool].max_keepalive_connections cannot exceed max_connections")
    expiry = section.get("keepalive_expiry_seconds", DEFAULT_POOL_KEEPALIVE_EXPIRY)
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not 0 < expiry <= MAX_POOL_KEEPALIVE_EXPIRY:
        raise DatabaseConfigurationError(f"configs/nexus.toml [model_connection_pool].keepalive_expiry_seconds must be > 0 and <= {MAX_POOL_KEEPALIVE_EXPIRY:g}")
    return ConnectionPoolSettings(max_connections, max_keepalive, float(expiry))


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
