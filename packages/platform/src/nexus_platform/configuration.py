"""Deployment configuration readers for the platform, backed by ``configs/nexus.toml``.

Paths are relative to the deployment working directory. Environment variables and dotenv files
are never read: every operator setting lives in the TOML file. Errors intentionally omit parser
details and secret values. Each reader accepts an optional ``path`` for tests and tooling.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from nexus_core.deployment import DeploymentConfigError, CONFIG_RELATIVE_PATH, load_config, section

#: Configuration errors raised by the platform readers; same type as the shared deployment error.
DatabaseConfigurationError = DeploymentConfigError

_FILE = CONFIG_RELATIVE_PATH.as_posix()


#: Default for ``[platform].max_concurrent_sessions``: sessions holding queued, started or unknown work.
DEFAULT_MAX_CONCURRENT_SESSIONS = 8


def max_concurrent_sessions(path: Path | None = None) -> int:
    """Return the global active-session cap from ``[platform]``.

    Absent file or key yields the default. A malformed file or a non-positive integer raises
    DatabaseConfigurationError so that a typo cannot silently lift the cap.
    """
    value = section("platform", path).get("max_concurrent_sessions", DEFAULT_MAX_CONCURRENT_SESSIONS)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DatabaseConfigurationError(f"{_FILE} [platform].max_concurrent_sessions must be a positive integer")
    return value


#: Authentication modes accepted in ``[auth].mode``; the API decides what each one means.
AUTH_MODES = ("development", "session", "external")
DEFAULT_DEV_USER_ID = "local-developer"


@dataclass(frozen=True)
class AuthFileSettings:
    """Values from ``[auth]``; ``None`` means the key is absent.

    ``cookie_secure`` defaults to True. Set it to false only for local HTTP development.
    """
    mode: str | None = None
    dev_user_id: str | None = None
    cookie_secure: bool = True
    # `[auth].registration_enabled`: when false, self-service sign-up is refused (invitations still work).
    registration_enabled: bool = True


def auth_settings(path: Path | None = None) -> AuthFileSettings:
    """Read ``[auth]`` from the deployment file.

    Absent file or section yields defaults (mode unset, cookies Secure). A malformed file, an
    unknown mode, a blank dev_user_id or a non-boolean cookie_secure raises
    DatabaseConfigurationError, so a typo cannot silently change the sign-in model.
    """
    values = section("auth", path)
    mode = values.get("mode")
    if mode is not None:
        if not isinstance(mode, str) or mode.strip().casefold() not in AUTH_MODES:
            raise DatabaseConfigurationError(f"{_FILE} [auth].mode must be one of: {', '.join(AUTH_MODES)}")
        mode = mode.strip().casefold()
    dev_user_id = values.get("dev_user_id")
    if dev_user_id is not None:
        if not isinstance(dev_user_id, str) or not dev_user_id.strip():
            raise DatabaseConfigurationError(f"{_FILE} [auth].dev_user_id must be a non-empty string")
        dev_user_id = dev_user_id.strip()
    cookie_secure = values.get("cookie_secure", True)
    if not isinstance(cookie_secure, bool):
        raise DatabaseConfigurationError(f"{_FILE} [auth].cookie_secure must be true or false")
    registration_enabled = values.get("registration_enabled", True)
    if not isinstance(registration_enabled, bool):
        raise DatabaseConfigurationError(f"{_FILE} [auth].registration_enabled must be true or false")
    return AuthFileSettings(mode=mode, dev_user_id=dev_user_id, cookie_secure=cookie_secure,
                            registration_enabled=registration_enabled)


#: Default log level when ``[logging].level`` is absent.
DEFAULT_LOG_LEVEL = "INFO"


def logging_level(path: Path | None = None) -> str:
    """Return ``[logging].level`` (for example ``INFO`` or ``DEBUG``); absent means INFO."""
    value = section("logging", path).get("level", DEFAULT_LOG_LEVEL)
    if not isinstance(value, str) or not value.strip():
        raise DatabaseConfigurationError(f"{_FILE} [logging].level must be a non-empty string")
    return value.strip().upper()


def credential_encryption_key(path: Path | None = None) -> str | None:
    """Return ``[security].credential_encryption_key`` or None when it is absent or blank.

    The key is a Fernet key shared by API and worker. Validation of its format happens where it
    is used, so that this reader never echoes the value.
    """
    value = section("security", path).get("credential_encryption_key")
    if value is None:
        return None
    if not isinstance(value, str):
        raise DatabaseConfigurationError(f"{_FILE} [security].credential_encryption_key must be a string")
    return value.strip() or None


#: Names accepted in ``[model_credentials]``; they match the ``env://NAME`` handles stored with providers.
CREDENTIAL_NAME_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*")


def model_credentials(path: Path | None = None) -> dict[str, str]:
    """Return the named provider secrets from ``[model_credentials]``.

    Only names listed here can be resolved by Native Runs, so this table doubles as the allowlist.
    Values are returned as-is and must never be logged or shown to users.
    """
    values = section("model_credentials", path)
    result: dict[str, str] = {}
    for name, value in values.items():
        if not CREDENTIAL_NAME_PATTERN.fullmatch(name):
            raise DatabaseConfigurationError(f"{_FILE} [model_credentials] names must be upper-case identifiers")
        if not isinstance(value, str) or not value.strip():
            raise DatabaseConfigurationError(f"{_FILE} [model_credentials].{name} must be a non-empty string")
        result[name] = value.strip()
    return result


@dataclass(frozen=True)
class WeComSettings:
    """Enterprise WeChat internal-app login values from ``[wecom]``; empty strings mean not configured."""
    corp_id: str = ""
    agent_id: str = ""
    secret: str = field(default="", repr=False)
    redirect_uri: str = ""

    @property
    def configured(self) -> bool:
        return all((self.corp_id, self.agent_id, self.secret, self.redirect_uri))


def wecom_settings(path: Path | None = None) -> WeComSettings:
    """Read ``[wecom]``; absent keys leave the corresponding field empty (login then reports unavailable)."""
    values = section("wecom", path)
    fields = {}
    for key in ("corp_id", "agent_id", "secret", "redirect_uri"):
        value = values.get(key, "")
        if not isinstance(value, str):
            raise DatabaseConfigurationError(f"{_FILE} [wecom].{key} must be a string")
        fields[key] = value.strip()
    return WeComSettings(**fields)


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
    """Read ``[model_connection_pool]``; absent file or keys mean defaults.

    Invalid values raise DatabaseConfigurationError so that a typo cannot silently change pooling.
    Keep-alive connections may not exceed the total connection limit.
    """
    values = section("model_connection_pool", path)

    def integer(key: str, default: int, minimum: int) -> int:
        value = values.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise DatabaseConfigurationError(f"{_FILE} [model_connection_pool].{key} must be an integer >= {minimum}")
        return value

    max_connections = integer("max_connections", DEFAULT_POOL_MAX_CONNECTIONS, 1)
    max_keepalive = integer("max_keepalive_connections", DEFAULT_POOL_MAX_KEEPALIVE, 0)
    if max_keepalive > max_connections:
        raise DatabaseConfigurationError(f"{_FILE} [model_connection_pool].max_keepalive_connections cannot exceed max_connections")
    expiry = values.get("keepalive_expiry_seconds", DEFAULT_POOL_KEEPALIVE_EXPIRY)
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not 0 < expiry <= MAX_POOL_KEEPALIVE_EXPIRY:
        raise DatabaseConfigurationError(f"{_FILE} [model_connection_pool].keepalive_expiry_seconds must be > 0 and <= {MAX_POOL_KEEPALIVE_EXPIRY:g}")
    return ConnectionPoolSettings(max_connections, max_keepalive, float(expiry))


def resolve_database_url(explicit_url: str | None = None, path: Path | None = None) -> str:
    """Return the explicit URL, or ``[database].url`` from the deployment file.

    The explicit argument wins (used by Alembic tests). Missing file or key raises
    DatabaseConfigurationError: there is no environment fallback. Invalid values fail closed.
    Errors never include the connection string.
    """
    if explicit_url is not None:
        source, value = "explicit database URL", explicit_url
    else:
        source = f"{_FILE} [database].url"
        value = section("database", path).get("url")
        if value is None:
            raise DatabaseConfigurationError(f"Configure {_FILE} [database].url")
    if not isinstance(value, str) or not value.strip():
        raise DatabaseConfigurationError(f"{source} must be a non-empty database URL string")
    try:
        parsed = make_url(value)
        # Force validation of numeric ports without displaying SQLAlchemy's input.
        _ = parsed.port
    except (ArgumentError, ValueError, TypeError):
        raise DatabaseConfigurationError(f"{source} is not a valid database URL") from None
    return value


__all__ = [
    "AUTH_MODES",
    "AuthFileSettings",
    "ConnectionPoolSettings",
    "DEFAULT_DEV_USER_ID",
    "DatabaseConfigurationError",
    "WeComSettings",
    "auth_settings",
    "credential_encryption_key",
    "load_config",
    "logging_level",
    "max_concurrent_sessions",
    "model_connection_pool",
    "model_credentials",
    "resolve_database_url",
    "watchdog_settings",
    "wecom_settings",
]


def watchdog_settings(path: Path | None = None):
    """Read ``[watchdog]``; absent file or keys mean the run-watchdog defaults.

    Invalid values raise DatabaseConfigurationError so that a typo cannot silently disable or
    over-trigger the watchdog. The interval has a floor so a bad value cannot poll the database in a tight loop.
    """
    from .runs.watchdog import (DEFAULT_IDLE_SECONDS, DEFAULT_INTERVAL_SECONDS, DEFAULT_REPEAT_THRESHOLD,
                                WatchdogSettings)
    values = section("watchdog", path)

    def integer(key: str, default: int, minimum: int) -> int:
        value = values.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise DatabaseConfigurationError(f"{_FILE} [watchdog].{key} must be an integer >= {minimum}")
        return value

    return WatchdogSettings(
        idle_seconds=integer("idle_seconds", DEFAULT_IDLE_SECONDS, 30),
        repeat_threshold=integer("repeat_threshold", DEFAULT_REPEAT_THRESHOLD, 2),
        interval_seconds=integer("interval_seconds", DEFAULT_INTERVAL_SECONDS, 5),
    )


def skill_scripts_allowed(path: Path | None = None) -> bool:
    """Return ``[skills].allow_local_scripts``; absent means False.

    Enabling this is one of three conditions for running skill scripts (proposal 2026-11-04-skill-scripts,
    section 6). It never enables scripts by itself: the auth mode and the execution backend are checked
    where scripts would run.
    """
    value = section("skills", path).get("allow_local_scripts", False)
    if not isinstance(value, bool):
        raise DatabaseConfigurationError(f"{_FILE} [skills].allow_local_scripts must be true or false")
    return value


def skill_scripts_gate(*, auth_mode: str | None, backend: str | None, config_enabled: bool) -> bool:
    """Return True only when all proposal conditions hold: config flag, development auth mode, local backend.

    The API bind address is not part of this check: it is a process argument, not configuration, so
    it is verified by the startup entry point instead (open question in the proposal's tasks 1.4).
    """
    return bool(config_enabled) and auth_mode == "development" and backend == "local"
