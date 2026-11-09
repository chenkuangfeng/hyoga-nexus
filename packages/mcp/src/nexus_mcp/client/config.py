"""Connection-parameter validation, header hardening and fingerprints.

Validation mirrors deer-flow ``mcp/headers.py`` (``illegal_header_value_reason``)
and ``mcp/client.py`` (``build_server_params``): a header value is refused when
``httpx`` would either raise ``UnicodeEncodeError`` (non-ASCII) or when h11 would
reject it (NUL/vertical whitespace, leading or trailing SP/HTAB). Error messages
name the header, never the value, so a credential cannot leak through an exception.

The fingerprint follows Octop ``fingerprint_mcp_spec``'s key set but, per the
hyoga-nexus spec R3, secret values never enter the digest: ``headers`` / ``env``
contribute their sorted keys plus any credential-reference ids instead of values.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets

from .errors import McpError

TRANSPORTS = ("stdio", "streamable_http", "sse")
#: Authentication modes. Static header/env credentials remain the default; `oauth` adds a
#: per-principal bearer token at execution time (openspec 2026-11-08-mcp, 1.8).
AUTH_TYPES = ("none", "oauth")
#: What h11 refuses inside a header field value: NUL and the vertical-whitespace
#: characters. SP/HTAB are legal *between* visible characters but not at either end.
_FORBIDDEN_HEADER_VALUE_CHARS = re.compile(r"[\x00\n\x0b\x0c\r]")
#: A header/env value that names a stored credential reference instead of a literal secret.
_REF_KEY = "$credential_ref"


def is_secret_reference(value: object) -> bool:
    """True for a value shaped like ``{"$credential_ref": "<uuid>"}``."""
    return isinstance(value, dict) and set(value) == {_REF_KEY} and isinstance(value.get(_REF_KEY), str)


def illegal_header_value_reason(value: str) -> str | None:
    """Explain why `value` cannot be sent as an HTTP header value, or ``None``.

    Mirrors what the transport enforces without repeating the value, so callers
    fail closed with a message that names the header instead of leaking it.
    """
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return "contains characters outside ASCII"
    if _FORBIDDEN_HEADER_VALUE_CHARS.search(value):
        return "contains a line break or another forbidden control character"
    if value != value.strip(" \t"):
        return "has leading or trailing whitespace"
    return None


def validate_header_value(name: str, value: str) -> str:
    """Raise with a non-leaking message when `value` cannot cross the transport."""
    if not isinstance(value, str):
        raise McpError(f"Header {name!r} must be a string", code="invalid_configuration")
    reason = illegal_header_value_reason(value)
    if reason is not None:
        raise McpError(f"Header {name!r} cannot be sent: it {reason}", code="invalid_configuration")
    return value


def normalize_headers(headers: object) -> dict[str, object]:
    """Case-insensitive merge of header entries: a later key replaces an earlier one of any case.

    Ported from deer-flow ``apply_header_overrides``: the existing spelling wins, and any key
    differing only in case is removed, so the result never carries one header under two spellings
    (which would leak a credential through httpx's duplicate-header exception).
    """
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise McpError("headers must be an object", code="invalid_configuration")
    merged: dict[str, object] = {}
    lookup: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not key:
            raise McpError("Header names must be non-empty strings", code="invalid_configuration")
        if isinstance(value, str):
            value = validate_header_value(key, value)
        elif not is_secret_reference(value):
            raise McpError(f"Header {key!r} must be a string or credential reference", code="invalid_configuration")
        lowered = key.casefold()
        lookup.setdefault(lowered, key)
        canonical = lookup[lowered]
        for existing in [k for k in merged if k != canonical and k.casefold() == lowered]:
            del merged[existing]
        merged[canonical] = value
    return merged


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise McpError(f"{field} must be a list of strings", code="invalid_configuration")
    return list(value)


def _string_map(value: object, field: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise McpError(f"{field} must be an object", code="invalid_configuration")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise McpError(f"{field} keys must be non-empty strings", code="invalid_configuration")
        if isinstance(item, str):
            result[key] = item
        elif is_secret_reference(item):
            result[key] = item
        else:
            raise McpError(f"{field}.{key} must be a string or credential reference", code="invalid_configuration")
    return result


def _http_url(url: object) -> str:
    if not isinstance(url, str) or not url:
        raise McpError("url is required for HTTP transports", code="invalid_configuration")
    if not url.lower().startswith(("http://", "https://")):
        raise McpError("url must be http or https", code="invalid_configuration")
    return url


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise McpError(f"{field} must be a non-empty string", code="invalid_configuration")
    return value.strip()


def _oauth_block(raw: object) -> dict[str, object]:
    """Normalize the optional OAuth settings of an HTTP/SSE connection.

    Only references, endpoints and scopes live here: access tokens are stored per principal
    by the platform, never in a service's config. A client secret may still be a plain string
    (pre-registered client) or a credential reference, matching the static-header path.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise McpError("oauth must be an object", code="invalid_configuration")
    scopes = raw.get("scopes")
    if scopes is None:
        scopes = []
    if not isinstance(scopes, list) or not all(isinstance(item, str) and item for item in scopes):
        raise McpError("oauth.scopes must be a list of non-empty strings", code="invalid_configuration")
    client_secret = raw.get("client_secret")
    if isinstance(client_secret, str):
        client_secret = validate_header_value("client_secret", client_secret)
    elif client_secret is not None and not is_secret_reference(client_secret):
        raise McpError("oauth.client_secret must be a string or credential reference",
                       code="invalid_configuration")
    metadata_url = raw.get("auth_server_metadata_url")
    if metadata_url is not None:
        metadata_url = _http_url(metadata_url)
    return {
        "scopes": list(scopes),
        "client_id": _optional_string(raw.get("client_id"), "oauth.client_id"),
        "client_secret": client_secret,
        "auth_server_metadata_url": metadata_url,
    }


def validate_config(config: dict | None) -> dict:
    """Normalize a stored config dict and reject unknown or malformed connection parameters.

    Credential-reference markers are preserved here; the platform resolves them before calling
    `discover` / `call`, which then refuse anything still unresolved.
    """
    if not isinstance(config, dict):
        raise McpError("config must be an object", code="invalid_configuration")
    transport = config.get("transport")
    if transport not in TRANSPORTS:
        raise McpError(f"Unknown transport {transport!r}", code="invalid_configuration")
    result: dict[str, object] = {"transport": transport}
    timeout = config.get("timeout", 30)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise McpError("timeout must be a positive number", code="invalid_configuration")
    result["timeout"] = float(timeout)
    auth_type = config.get("auth_type", "none")
    if auth_type not in AUTH_TYPES:
        raise McpError(f"Unknown auth_type {auth_type!r}", code="invalid_configuration")
    if transport == "stdio":
        if auth_type != "none":
            raise McpError("OAuth is only available for HTTP transports", code="invalid_configuration")
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise McpError("command is required for stdio", code="invalid_configuration")
        result["command"] = command.strip()
        result["args"] = _string_list(config.get("args"), "args")
        result["env"] = _string_map(config.get("env"), "env")
    else:
        result["url"] = _http_url(config.get("url"))
        result["headers"] = normalize_headers(config.get("headers"))
        if transport == "sse":
            sse_read_timeout = config.get("sse_read_timeout", 300)
            if not isinstance(sse_read_timeout, (int, float)) or sse_read_timeout <= 0:
                raise McpError("sse_read_timeout must be a positive number", code="invalid_configuration")
            result["sse_read_timeout"] = float(sse_read_timeout)
    result["auth_type"] = auth_type
    if auth_type == "oauth":
        result["oauth"] = _oauth_block(config.get("oauth"))
    return result


def assert_resolved(config: dict) -> None:
    """Refuse to connect while any credential reference is still unresolved."""
    for section in ("headers", "env"):
        mapping = config.get(section)
        if isinstance(mapping, dict):
            for key, value in mapping.items():
                if is_secret_reference(value):
                    raise McpError(f"Credential {key!r} is unresolved", code="mcp_unresolved_reference")
    oauth = config.get("oauth")
    if isinstance(oauth, dict) and is_secret_reference(oauth.get("client_secret")):
        raise McpError("OAuth client secret is unresolved", code="mcp_unresolved_reference")


def replace_authorization(headers: dict, value: str) -> dict:
    """Return a copy of `headers` with one `Authorization` entry (case-insensitive replacement).

    The dynamic OAuth token takes precedence over any static header; keeping a single spelling
    avoids the duplicate-header failure that could echo the credential in an exception.
    """
    validate_header_value("Authorization", value)
    merged: dict[str, str] = {}
    replaced = False
    for key, existing in (headers or {}).items():
        if key.casefold() == "authorization":
            if not replaced:
                merged[key] = value
                replaced = True
            continue
        merged[key] = existing
    if not replaced:
        merged["Authorization"] = value
    return merged


def _reference_id(value: object) -> str | None:
    return value.get(_REF_KEY) if is_secret_reference(value) else None


def fingerprint(config: dict) -> str:
    """A stable cache key over the connection parameters that determine which tools exist.

    Secret values never enter the digest: `headers` / `env` contribute their sorted keys plus any
    credential reference ids, so rotating a secret does not invalidate the tool cache while changing
    the endpoint, command or reference set does. The platform stores this on every discovery.
    """
    normalized = config if config.get("transport") in TRANSPORTS else validate_config(config)
    parts: dict[str, object] = {"transport": normalized["transport"]}
    if normalized["transport"] == "stdio":
        parts["command"] = normalized.get("command")
        parts["args"] = list(normalized.get("args") or [])
    else:
        parts["url"] = normalized.get("url")
        # OAuth changes which tools are visible and which token is presented; the client secret
        # and any access token never enter the digest (rotating them must not invalidate the cache).
        parts["auth_type"] = normalized.get("auth_type", "none")
        oauth = normalized.get("oauth")
        if isinstance(oauth, dict):
            parts["oauth"] = {
                "scopes": list(oauth.get("scopes") or []),
                "client_id": oauth.get("client_id"),
                "auth_server_metadata_url": oauth.get("auth_server_metadata_url"),
                "client_secret_reference": _reference_id(oauth.get("client_secret")),
            }
    for section in ("headers", "env"):
        mapping = normalized.get(section)
        if not isinstance(mapping, dict):
            parts[section] = []
            continue
        entries: list[str] = []
        for key, value in mapping.items():
            reference = _reference_id(value)
            entries.append(f"{key}={reference}" if reference else f"{key}")
        parts[section] = sorted(entries)
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def new_epoch() -> str:
    """A fresh opaque lifecycle-epoch token for a service (deer-flow ``lifecycle.py``).

    The platform bumps it whenever a service is deleted and later re-added with an identical
    fingerprint, so an old stdio session is never silently reused against the new incarnation.
    """
    return secrets.token_hex(32)
