"""Where enterprise-configured knowledge stores may connect (openspec 2026-11-11-enterprise-saas decision 9).

In a multi-enterprise deployment an enterprise administrator must not reach the deployment's own network or disk
through a vector store, storage backend or graph store:

- file-backed stores (the ``sqlite`` vector engine and the ``local`` storage provider) take a server path, so an
  enterprise may configure them only when ``[knowledge].allow_tenant_local_stores = true`` (single-company
  deployments). The builtin stores are configured by the operator and are not affected;
- network stores (``url`` or ``dsn``) must name a host whose every address is publicly routable, unless the host is
  listed in ``[model_network].private_host_allowlist`` (the same list that admits private model providers).

The check runs when a configuration is saved or tested. It does not pin addresses for later connections; DNS that
changes after saving is not caught here (recorded as a limitation in the proposal).
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any, Mapping
from urllib.parse import urlsplit

from nexus_core.deployment import DeploymentConfigError, section
from nexus_platform.errors import InvalidConfiguration

FILE_BACKED = frozenset({('vector', 'sqlite'), ('storage', 'local')})


def _flag(name: str) -> bool:
    try:
        return section('knowledge').get(name, False) is True
    except DeploymentConfigError:
        return False


def _allowlist() -> set[str]:
    try:
        values = section('model_network').get('private_host_allowlist', [])
    except DeploymentConfigError:
        return set()
    if not isinstance(values, list):
        return set()
    return {str(item).strip().lower() for item in values if str(item).strip()}


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split('%')[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_host(host: str) -> None:
    """Refuse a host that is, or resolves to, a non-public address unless it is allowlisted."""
    host = (host or '').strip().lower()
    if not host:
        raise InvalidConfiguration('store_address_invalid')
    if host in _allowlist():
        return
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
        except OSError:
            raise InvalidConfiguration('store_address_unresolvable') from None
    if not addresses or not all(_public(address) for address in addresses):
        raise InvalidConfiguration('store_destination_denied: add the host to '
                                   '[model_network].private_host_allowlist to use a private address')


def _host_of(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.hostname:
        raise InvalidConfiguration('store_address_invalid')
    return parsed.hostname


def check_store(kind: str, engine: str, config: Mapping[str, Any]) -> None:
    """Validate one store configuration. ``kind`` is ``vector``, ``storage`` or ``graph``."""
    if (kind, engine) in FILE_BACKED:
        if not _flag('allow_tenant_local_stores'):
            raise InvalidConfiguration('local_store_not_allowed: file-backed stores are configured by the operator')
        return
    for key in ('url', 'dsn', 'endpoint'):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            check_host(_host_of(value.strip()))
