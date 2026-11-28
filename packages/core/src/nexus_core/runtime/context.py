"""Vendor-neutral, provenance-bearing inputs to one model context assembly.

These values contain data only. Authorization and resource loading belong to the platform;
rendering belongs to the Runtime. A content digest identifies bytes, never permission.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal, Protocol

from .models import ModelMessage


def context_digest(value: object) -> str:
    """Hash canonical JSON without accepting reprs, callbacks or vendor objects."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, order=True)
class ContextDependency:
    """An injected source identity/version; the platform rechecks its current accessibility."""
    kind: str
    resource_id: str
    version: str
    source_run_id: str | None = None
    permission: Literal['read', 'use'] = 'use'

    def __post_init__(self) -> None:
        if (any(not isinstance(v, str) or not v for v in (self.kind, self.resource_id))
                or not isinstance(self.version, str) or (not self.version and self.kind != 'resource')
                or (self.source_run_id is not None and not isinstance(self.source_run_id, str))
                or self.permission not in ('read', 'use')):
            raise ValueError('context_dependency_invalid')


@dataclass(frozen=True)
class ContextBlock:
    """One named contribution, with placement and trust assigned by the host.

    Text is not interpreted as permission. The digest is calculated from the text, so callers
    cannot associate a cached hash with different bytes. Duplicate keys are rejected by assembly.
    """
    key: str
    source: str
    role: Literal['system', 'user']
    placement: Literal['system_static', 'system_catalog', 'history_prefix', 'turn_tail']
    order: int
    text: str
    lifetime: Literal['session', 'run', 'step'] = 'run'
    trust: Literal['instructions', 'reference'] = 'reference'
    dependencies: tuple[ContextDependency, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, 'dependencies', tuple(self.dependencies))
        if (not isinstance(self.text, str) or not isinstance(self.key, str) or not self.key
                or not isinstance(self.source, str) or not self.source or type(self.order) is not int
                or any(not isinstance(d, ContextDependency) for d in self.dependencies)
                or self.role not in ('system', 'user')
                or self.placement not in ('system_static', 'system_catalog', 'history_prefix', 'turn_tail')
                or self.lifetime not in ('session', 'run', 'step')
                or self.trust not in ('instructions', 'reference')
                or (self.role == 'system') != self.placement.startswith('system_')):
            raise ValueError('context_block_invalid')

    @property
    def digest(self) -> str:
        """Stable hash of this contribution's exact text."""
        return context_digest(self.text)


@dataclass(frozen=True)
class ContextBuildInput:
    """Authorized, credential-free input exposed to a trusted context provider."""
    tenant_id: str
    principal_id: str
    session_id: str
    run_id: str
    agent_version_id: str
    step: int
    user_message_id: str | None
    query: str
    as_of: datetime
    dependencies: tuple[ContextDependency, ...] = ()


@dataclass(frozen=True)
class AssemblyManifest:
    """Versioned provenance ledger; stores hashes and source references, never body text."""
    schema_version: int
    assembly_id: str
    layout_version: str
    source_watermark: int
    block_digests: tuple[tuple[str, str], ...]
    dependencies: tuple[ContextDependency, ...]
    tools_digest: str = ''

    def to_dict(self) -> dict:
        """Plain JSON data suitable for durable storage and cross-process recovery."""
        return asdict(self)


@dataclass(frozen=True)
class RunContextSnapshot:
    """Run-local content values; no shared mutable schema or execution handles."""
    blocks: tuple[ContextBlock, ...]
    messages: tuple[ModelMessage, ...]
    manifest: AssemblyManifest


class ContextProvider(Protocol):
    """Application-registered async provider. It may return only host-approved context blocks."""
    async def provide(self, context: ContextBuildInput) -> tuple[ContextBlock, ...]: ...
