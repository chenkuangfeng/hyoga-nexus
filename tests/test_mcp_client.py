"""MCP client pure logic: config validation, fingerprints, names, risk policy (openspec 2026-11-08-mcp)."""
import pytest

from nexus_mcp.client import (
    McpError,
    fingerprint,
    illegal_header_value_reason,
    normalize_headers,
    validate_config,
)
from nexus_mcp.client.names import (
    external_description,
    registered_name,
    sanitize_name,
    tool_ref,
    valid_external_tool_name,
)
from nexus_platform.mcp.policy import (
    declared_risk,
    effective_risk,
    fail_close_action,
    observe_declared,
    pending_downgrade,
    risk_action,
)


# --- config validation -------------------------------------------------------

def test_stdio_requires_command_and_strings():
    with pytest.raises(McpError) as exc:
        validate_config({"transport": "stdio"})
    assert exc.value.code == "invalid_configuration"
    with pytest.raises(McpError):
        validate_config({"transport": "stdio", "command": "node", "args": "not-a-list"})
    with pytest.raises(McpError):
        validate_config({"transport": "stdio", "command": "node", "env": {"K": 1}})


def test_http_requires_http_url():
    with pytest.raises(McpError):
        validate_config({"transport": "streamable_http"})
    with pytest.raises(McpError):
        validate_config({"transport": "streamable_http", "url": "ftp://x"})
    assert validate_config({"transport": "streamable_http", "url": "https://x"}).get("url") == "https://x"


def test_unknown_transport_rejected():
    with pytest.raises(McpError) as exc:
        validate_config({"transport": "websocket", "url": "https://x"})
    assert exc.value.code == "invalid_configuration"


def test_header_value_hardening_matches_transport():
    assert illegal_header_value_reason("ok") is None
    assert illegal_header_value_reason(" has space ") == "has leading or trailing whitespace"
    assert illegal_header_value_reason("a\nb") == "contains a line break or another forbidden control character"
    assert illegal_header_value_reason("\tt") == "has leading or trailing whitespace"
    assert illegal_header_value_reason("雪") == "contains characters outside ASCII"


def test_header_error_names_header_not_value():
    with pytest.raises(McpError) as exc:
        validate_config({"transport": "sse", "url": "http://x", "headers": {"Authorization": "secret\nleak"}})
    assert "secret" not in str(exc.value)
    assert "Authorization" in str(exc.value)


def test_headers_merge_case_insensitively_keeping_first_spelling():
    merged = normalize_headers({"Authorization": "a", "authorization": "b", "X-One": "1"})
    assert merged == {"Authorization": "b", "X-One": "1"}


def test_credential_references_survive_validation_but_not_fingerprint_values():
    config = {"transport": "stdio", "command": "node", "env": {"TOKEN": {"$credential_ref": "u-1"}}}
    assert validate_config(config)["env"]["TOKEN"] == {"$credential_ref": "u-1"}
    ref = fingerprint(config)
    secret = fingerprint({"transport": "stdio", "command": "node", "env": {"TOKEN": {"$credential_ref": "u-2"}}})
    assert ref != secret


def test_fingerprint_ignores_secret_values():
    a = fingerprint({"transport": "streamable_http", "url": "https://x", "headers": {"Authorization": "one"}})
    b = fingerprint({"transport": "streamable_http", "url": "https://x", "headers": {"Authorization": "two"}})
    assert a == b
    c = fingerprint({"transport": "streamable_http", "url": "https://x", "headers": {"X-Other": "one"}})
    assert a != c


# --- registration names ------------------------------------------------------

def test_registered_name_is_stable_and_ascii():
    name = registered_name("svc-1", "My Service!", "Get Weather-2")
    assert name.startswith("mcp_")
    assert len(name) <= 64
    assert all(c.isascii() for c in name)
    assert name == registered_name("svc-1", "My Service!", "Get Weather-2")


def test_registered_name_hashes_identity_not_only_hint():
    a = registered_name("svc-1", "service", "tool")
    b = registered_name("svc-2", "service", "tool")
    assert a != b
    assert a.split("_")[-1] != b.split("_")[-1]


def test_sanitize_name_folds_to_safe_charset():
    assert sanitize_name("My Service!") == "my_service"
    assert sanitize_name("A-B c_d") == "a_b_c_d"


def test_external_tool_names_are_dropped_when_unsafe():
    assert valid_external_tool_name("safe_name-1") == "safe_name-1"
    assert valid_external_tool_name("bad name") is None
    assert valid_external_tool_name("line\nbreak") is None
    assert valid_external_tool_name(123) is None


def test_external_description_prefixes_source():
    assert external_description("svc", "id-1", "tool", "does things") == (
        '[MCP service "svc", server_id="id-1", tool="tool" (external)] does things'
    )


def test_tool_ref_binds_schema():
    assert tool_ref("svc", "tool", {"type": "object"}) != tool_ref("svc", "tool", {"type": "object", "properties": {}})


# --- risk policy (WeKnora mcp_risk.go) ---------------------------------------

def test_declared_risk_only_readonly_lowers():
    assert declared_risk(True) == "read"
    assert declared_risk(False) == "write"


def test_effective_risk_precedence():
    assert effective_risk(None, None, "write") == "write"
    assert effective_risk("destructive", None, "write") == "destructive"
    assert effective_risk(None, "write", "read") == "write"
    assert effective_risk(None, "read", "write") == "write"
    assert effective_risk(None, None, "read") == "read"


def test_observe_declared_only_rises():
    assert observe_declared(None, None, "write") == "write"
    assert observe_declared(None, "write", "read") is None
    assert observe_declared(None, "read", "write") == "write"


def test_pending_downgrade_needs_workspace_confirmation():
    assert pending_downgrade(None, "write", "read") is True
    assert pending_downgrade("read", "write", "read") is False
    assert pending_downgrade(None, "read", "read") is False


def test_fail_close_is_write_plus_approval():
    assert risk_action(None, None, "write") == ("write", False)
    assert fail_close_action() == ("write", True)
