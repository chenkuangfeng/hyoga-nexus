"""Parser engine configuration and selection (openspec 2026-11-06-knowledge-base K4).

- A space keeps one configuration for the external engines (`knowledge_parser_configs`), written by space admins;
  secrets are encrypted and masked on read, a masked value sent back keeps the stored secret.
- A knowledge base picks an engine per file type with ``settings.chunking_config.parser_engine_rules`` (WeKnora
  ``ParserEngineRule``: ``{"file_types": ["pdf"], "engine": "mineru"}``); files without a rule use ``builtin``.
- :func:`engine_list` describes every engine for the settings page: implemented or planned, configured or not.

The HTTP client factory is injected by the worker (`set_http_client_factory`) so this module has no dependency on
the model transport; engines run only in the worker.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from nexus_core.platform import utc_now
from nexus_knowledge import capabilities
from nexus_knowledge.ingest import anydoc, engines
from nexus_knowledge.ingest.parse import suffix_of
from nexus_platform.authz.audit import audit
from nexus_platform.identity.service import require_membership
from nexus_platform.persistence.models import ParserEngineConfigRecord
from nexus_platform.tenants.service import ADMIN_ROLES
from . import stores

BUILTIN = 'builtin'
ANYDOC = 'anydoc'
_HTTP: list[Callable[[str], httpx.AsyncClient]] = []


def set_http_client_factory(factory: Callable[[str], httpx.AsyncClient] | None) -> None:
    _HTTP[:] = [factory] if factory else []


def http_client_for(url: str) -> httpx.AsyncClient:
    if not _HTTP:
        raise LookupError('no HTTP client factory is configured')
    return _HTTP[0](url)


def _reveal(tenant_id: UUID, config: Mapping[str, Any]) -> dict[str, Any]:
    return {k: stores._open(tenant_id, v) if k in engines.SECRET_KEYS and isinstance(v, str) else v
            for k, v in config.items()}


def _mask(config: Mapping[str, Any]) -> dict[str, Any]:
    return {k: stores.MASK if k in engines.SECRET_KEYS and v else v for k, v in config.items()}


def load_config(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Decrypted engine settings of a space (worker use)."""
    row = db.get(ParserEngineConfigRecord, tenant_id)
    return _reveal(tenant_id, row.config) if row else {}


def masked_config(db: Session, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    require_membership(db, tenant_id, user_id)
    row = db.get(ParserEngineConfigRecord, tenant_id)
    return _mask(row.config) if row else {}


def save_config(db: Session, tenant_id: UUID, user_id: UUID, submitted: Mapping[str, Any]) -> dict[str, Any]:
    """Replace the space's engine settings. ``MASK`` keeps a stored secret; unknown keys are rejected."""
    require_membership(db, tenant_id, user_id, roles=ADMIN_ROLES)
    allowed = {key for engine in engines.EXTERNAL.values() for key in engine.required} | _OPTIONAL
    unknown = sorted(set(submitted) - allowed)
    if unknown:
        raise ValueError(f'unknown parser setting: {", ".join(unknown)}')
    row = db.get(ParserEngineConfigRecord, tenant_id)
    stored = row.config if row else {}
    # Secret fields are encrypted under the engine secret names too (stores.SECRET_FIELDS has the generic ones).
    sealed: dict[str, Any] = {}
    for key, value in submitted.items():
        if key in engines.SECRET_KEYS and isinstance(value, str):
            if value == stores.MASK:
                if key in stored:
                    sealed[key] = stored[key]
            elif value:
                sealed[key] = stores._seal(tenant_id, value)
        elif value not in (None, ''):
            sealed[key] = value
    now = utc_now()
    if row is None:
        db.add(ParserEngineConfigRecord(tenant_id=tenant_id, config=sealed, updated_by=user_id, updated_at=now))
    else:
        row.config, row.updated_by, row.updated_at = sealed, user_id, now
    audit(db, tenant_id, user_id, 'parser_config.updated', 'tenant', str(tenant_id), {'keys': sorted(sealed)})
    return _mask(sealed)


_OPTIONAL = frozenset({
    'mineru_server_api_key', 'mineru_model', 'mineru_vlm_server_url', 'mineru_enable_formula', 'mineru_enable_table',
    'mineru_parse_method', 'mineru_enable_ocr', 'mineru_language', 'mineru_cloud_model', 'mineru_cloud_enable_formula',
    'mineru_cloud_enable_table', 'mineru_cloud_enable_ocr', 'mineru_cloud_language', 'paddleocr_vl_use_seal_recognition',
    'paddleocr_vl_use_chart_recognition', 'paddleocr_vl_cloud_model', 'paddleocr_vl_cloud_use_seal_recognition',
    'paddleocr_vl_cloud_use_chart_recognition', 'mineru_tier', 'docreader_addr', 'docreader_transport'})


def engine_for(settings: Mapping[str, Any] | None, filename: str) -> str:
    """Engine chosen for a file by the base's rules (first matching rule wins).

    Without a rule the in-process ``anydoc`` engine takes the formats the builtin parser cannot read (legacy Office,
    OpenDocument, RTF, EPUB, HTML - WeKnora's "prefer anydoc when available"); everything else uses ``builtin``.
    """
    suffix = suffix_of(filename).lstrip('.')
    for rule in ((settings or {}).get('chunking_config') or {}).get('parser_engine_rules') or []:
        if not isinstance(rule, dict):
            continue
        types = {str(t).lstrip('.').lower() for t in rule.get('file_types') or []}
        if suffix in types and rule.get('engine'):
            return str(rule['engine'])
    return ANYDOC if suffix in anydoc.EXTRA else BUILTIN


def engine_list(config: Mapping[str, Any], builtin_types: list[str]) -> list[dict[str, Any]]:
    """Every engine of the catalog with file types, availability and the reason when it is not usable."""
    out = []
    for row in capabilities.snapshot():
        if row['group'] != 'parser_engine':
            continue
        name = row['key']
        engine = engines.EXTERNAL.get(name)
        if name == ANYDOC:
            item = {'Name': name, 'Description': '进程内 Office / 电子书转换（无需外部服务）',
                    'FileTypes': list(anydoc.SUPPORTED), 'Available': True, 'UnavailableReason': ''}
        elif name in (BUILTIN, 'simple'):
            item = {'Name': name, 'Description': row['label'], 'FileTypes': builtin_types, 'Available': True,
                    'UnavailableReason': ''}
        elif engine is not None:
            reason = engine.unavailable_reason(config)
            item = {'Name': name, 'Description': engine.description, 'FileTypes': list(engine.file_types),
                    'Available': not reason, 'UnavailableReason': reason}
        else:
            item = {'Name': name, 'Description': row['label'], 'FileTypes': [], 'Available': False,
                    'UnavailableReason': f'待实现 · {row["stage"]}' if row['stage'] else '待实现'}
        out.append(item)
    return out


for _name in engines.EXTERNAL:
    capabilities.mark_available('parser_engine', _name, verified=False)
capabilities.mark_available('parser_engine', 'simple')
capabilities.mark_available('parser_engine', ANYDOC)  # verified against the fixtures WeKnora tests with
