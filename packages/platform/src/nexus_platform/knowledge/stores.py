"""Vector store and storage backend registries of a space (openspec 2026-11-06-knowledge-base K1.6).

A knowledge base names a registered vector store and storage backend, or NULL for the builtin ones: the
SQLite vector store at ``[knowledge].data_dir/vectors.db`` and the local directory ``data_dir/files``. Builtin
stores are not rows; they appear in listings with the fixed ids ``builtin``.

Secrets (``password``, ``api_key``, ``token``, ``dsn``, ``secret_key``...) are encrypted with the deployment
credential key, bound to the store id, and never returned: listings show ``MASK`` in their place, and an
update that sends ``MASK`` back keeps the stored value. Engines and providers must be ``available`` in the
capability catalog (``capability_planned`` otherwise). A store used by a knowledge base cannot be deleted
and cannot change engine.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import new_id, utc_now
from nexus_knowledge import capabilities
from nexus_knowledge.index import VectorIndex, open_index
from nexus_knowledge.providers import BlobStore, open_blob_store
from nexus_platform.authz.audit import audit
from nexus_platform.configuration import knowledge_settings
from nexus_platform.knowledge.connections import check_store
from nexus_platform.errors import Conflict, NotFound, ServiceUnavailable
from nexus_platform.identity.service import require_membership
from nexus_platform.models.provider_settings import cipher
from nexus_platform.persistence.models import (GraphStoreRecord, KnowledgeBaseRecord, StorageBackendRecord,
                                               VectorStoreRecord)
from nexus_platform.tenants.service import ADMIN_ROLES

BUILTIN = 'builtin'
MASK = '******'
SECRET_FIELDS = frozenset({'password', 'api_key', 'token', 'dsn', 'secret_key', 'secret_id', 'access_key_secret'})
_PREFIX = 'enc:'


def _seal(store_id: UUID, value: str) -> str:
    return _PREFIX + cipher().encrypt((str(store_id) + '\n' + value).encode()).decode()


def _open(store_id: UUID, token: str) -> str:
    if not token.startswith(_PREFIX):
        return token
    try:
        identity, value = cipher().decrypt(token[len(_PREFIX):].encode()).decode().split('\n', 1)
    except (InvalidToken, ValueError):
        raise ServiceUnavailable('Stored connection secret cannot be decrypted') from None
    if identity != str(store_id):
        raise ServiceUnavailable('Stored connection secret cannot be decrypted')
    return value


def seal_config(store_id: UUID, submitted: dict[str, Any], stored: dict[str, Any] | None = None) -> dict[str, Any]:
    """Encrypt secret fields; ``MASK`` keeps the stored secret, an empty string clears it."""
    out: dict[str, Any] = {}
    for key, value in submitted.items():
        if key in SECRET_FIELDS and isinstance(value, str):
            if value == MASK:
                if stored and key in stored:
                    out[key] = stored[key]
            elif value:
                out[key] = _seal(store_id, value)
        else:
            out[key] = value
    return out


def reveal_config(store_id: UUID, stored: dict[str, Any]) -> dict[str, Any]:
    return {key: _open(store_id, value) if key in SECRET_FIELDS and isinstance(value, str) else value
            for key, value in stored.items()}


def masked_config(stored: dict[str, Any]) -> dict[str, Any]:
    return {key: MASK if key in SECRET_FIELDS and value else value for key, value in stored.items()}


# ---------------------------------------------------------------- builtin stores

def builtin_vector_index() -> VectorIndex:
    return open_index('sqlite', {'path': str(knowledge_settings().vectors_path)})


def builtin_blob_store() -> BlobStore:
    return open_blob_store('local', {'root': str(knowledge_settings().files_dir)})


def vector_index_for(db: Session, kb: KnowledgeBaseRecord) -> VectorIndex:
    if kb.vector_store_id is None:
        return builtin_vector_index()
    row = db.get(VectorStoreRecord, kb.vector_store_id)
    if row is None:
        raise NotFound('Vector store not found')
    return open_index(row.engine, reveal_config(row.id, row.connection_config), row.index_config)


def blob_store_for(db: Session, kb: KnowledgeBaseRecord) -> BlobStore:
    if kb.storage_backend_id is None:
        return builtin_blob_store()
    row = db.get(StorageBackendRecord, kb.storage_backend_id)
    if row is None:
        raise NotFound('Storage backend not found')
    return open_blob_store(row.provider, reveal_config(row.id, row.config))


def engine_of(db: Session, kb: KnowledgeBaseRecord) -> str:
    if kb.vector_store_id is None:
        return 'sqlite'
    row = db.get(VectorStoreRecord, kb.vector_store_id)
    return row.engine if row else 'sqlite'


# ---------------------------------------------------------------- registry views

def _builtin_vector_view() -> dict[str, Any]:
    return {'id': BUILTIN, 'name': '内置 SQLite', 'engine': 'sqlite', 'builtin': True, 'connection_config': {
        'path': str(knowledge_settings().vectors_path)}, 'index_config': {}}


def _builtin_storage_view() -> dict[str, Any]:
    return {'id': BUILTIN, 'name': '本地目录', 'provider': 'local', 'builtin': True, 'config': {
        'root': str(knowledge_settings().files_dir)}}


def vector_store_view(row: VectorStoreRecord) -> dict[str, Any]:
    return {'id': str(row.id), 'name': row.name, 'engine': row.engine, 'builtin': False,
            'connection_config': masked_config(row.connection_config), 'index_config': dict(row.index_config),
            'created_at': row.created_at.isoformat(), 'updated_at': row.updated_at.isoformat()}


def storage_backend_view(row: StorageBackendRecord) -> dict[str, Any]:
    return {'id': str(row.id), 'name': row.name, 'provider': row.provider, 'builtin': False,
            'config': masked_config(row.config), 'created_at': row.created_at.isoformat(),
            'updated_at': row.updated_at.isoformat()}


def list_vector_stores(db: Session, tenant_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
    require_membership(db, tenant_id, user_id)
    rows = db.scalars(select(VectorStoreRecord).where(VectorStoreRecord.tenant_id == tenant_id)
                      .order_by(VectorStoreRecord.created_at)).all()
    return [_builtin_vector_view(), *(vector_store_view(row) for row in rows)]


def list_storage_backends(db: Session, tenant_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
    require_membership(db, tenant_id, user_id)
    rows = db.scalars(select(StorageBackendRecord).where(StorageBackendRecord.tenant_id == tenant_id)
                      .order_by(StorageBackendRecord.created_at)).all()
    return [_builtin_storage_view(), *(storage_backend_view(row) for row in rows)]


def _validate_name(name: str) -> str:
    name = (name or '').strip()
    if not name or len(name) > 160:
        raise ValueError('name must be 1-160 characters')
    return name


def create_vector_store(db: Session, tenant_id: UUID, user_id: UUID, *, name: str, engine: str,
                        connection_config: dict[str, Any], index_config: dict[str, Any]) -> VectorStoreRecord:
    """Space admins only. The engine must be implemented; the configuration must open an index."""
    require_membership(db, tenant_id, user_id, roles=ADMIN_ROLES)
    capabilities.require_available('vector_engine', engine)
    store_id, now = new_id(), utc_now()
    check_store('vector', engine, connection_config)
    sealed = seal_config(store_id, connection_config)
    open_index(engine, reveal_config(store_id, sealed), index_config)  # rejects unusable configuration early
    row = VectorStoreRecord(id=store_id, tenant_id=tenant_id, name=_validate_name(name), engine=engine,
                            connection_config=sealed, index_config=dict(index_config), created_by=user_id,
                            created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    audit(db, tenant_id, user_id, 'vector_store.created', 'vector_store', str(row.id), {'engine': engine})
    return row


def update_vector_store(db: Session, tenant_id: UUID, user_id: UUID, store_id: UUID, *, name: str,
                        connection_config: dict[str, Any], index_config: dict[str, Any]) -> VectorStoreRecord:
    require_membership(db, tenant_id, user_id, roles=ADMIN_ROLES)
    row = db.get(VectorStoreRecord, store_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound('Vector store not found')
    sealed = seal_config(row.id, connection_config, row.connection_config)
    check_store('vector', row.engine, reveal_config(row.id, sealed))
    open_index(row.engine, reveal_config(row.id, sealed), index_config)
    row.name, row.connection_config, row.index_config = _validate_name(name), sealed, dict(index_config)
    row.updated_at = utc_now()
    audit(db, tenant_id, user_id, 'vector_store.updated', 'vector_store', str(row.id), {})
    return row


def delete_vector_store(db: Session, tenant_id: UUID, user_id: UUID, store_id: UUID) -> None:
    require_membership(db, tenant_id, user_id, roles=ADMIN_ROLES)
    row = db.get(VectorStoreRecord, store_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound('Vector store not found')
    if db.scalar(select(KnowledgeBaseRecord.id).where(KnowledgeBaseRecord.vector_store_id == store_id)) is not None:
        raise Conflict('Vector store is used by a knowledge base')
    db.delete(row)
    audit(db, tenant_id, user_id, 'vector_store.deleted', 'vector_store', str(store_id), {})


def create_storage_backend(db: Session, tenant_id: UUID, user_id: UUID, *, name: str, provider: str,
                           config: dict[str, Any]) -> StorageBackendRecord:
    require_membership(db, tenant_id, user_id, roles=ADMIN_ROLES)
    capabilities.require_available('storage_provider', provider)
    check_store('storage', provider, config)
    backend_id, now = new_id(), utc_now()
    sealed = seal_config(backend_id, config)
    open_blob_store(provider, reveal_config(backend_id, sealed))
    row = StorageBackendRecord(id=backend_id, tenant_id=tenant_id, name=_validate_name(name), provider=provider,
                               config=sealed, created_by=user_id, created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    audit(db, tenant_id, user_id, 'storage_backend.created', 'storage_backend', str(row.id), {'provider': provider})
    return row


def delete_storage_backend(db: Session, tenant_id: UUID, user_id: UUID, backend_id: UUID) -> None:
    require_membership(db, tenant_id, user_id, roles=ADMIN_ROLES)
    row = db.get(StorageBackendRecord, backend_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound('Storage backend not found')
    if db.scalar(select(KnowledgeBaseRecord.id).where(KnowledgeBaseRecord.storage_backend_id == backend_id)) is not None:
        raise Conflict('Storage backend is used by a knowledge base')
    db.delete(row)
    audit(db, tenant_id, user_id, 'storage_backend.deleted', 'storage_backend', str(backend_id), {})


def vector_store_of_tenant(db: Session, tenant_id: UUID, store_id: str | None) -> VectorStoreRecord | None:
    """Resolve a store reference from a request: None / ``builtin`` → builtin; otherwise a row of this space."""
    if store_id in (None, '', BUILTIN):
        return None
    row = db.get(VectorStoreRecord, UUID(str(store_id)))
    if row is None or row.tenant_id != tenant_id:
        raise NotFound('Vector store not found')
    return row


def storage_backend_of_tenant(db: Session, tenant_id: UUID, backend_id: str | None) -> StorageBackendRecord | None:
    if backend_id in (None, '', BUILTIN):
        return None
    row = db.get(StorageBackendRecord, UUID(str(backend_id)))
    if row is None or row.tenant_id != tenant_id:
        raise NotFound('Storage backend not found')
    return row


# ---------------------------------------------------------------- graph stores (openspec 2026-11-06-knowledge-base K2.7)

def graph_store_view(row: GraphStoreRecord) -> dict[str, Any]:
    return {'id': str(row.id), 'name': row.name, 'engine': row.engine, 'builtin': False,
            'connection_config': masked_config(row.connection_config), 'created_at': row.created_at.isoformat(),
            'updated_at': row.updated_at.isoformat()}


def list_graph_stores(db: Session, tenant_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
    """Selectable graph stores: the builtin one first, then the space's registered stores."""
    require_membership(db, tenant_id, user_id)
    rows = db.scalars(select(GraphStoreRecord).where(GraphStoreRecord.tenant_id == tenant_id)
                      .order_by(GraphStoreRecord.created_at)).all()
    return [{'id': BUILTIN, 'name': '内置图存储', 'engine': 'builtin', 'builtin': True, 'connection_config': {}},
            *(graph_store_view(row) for row in rows)]


def create_graph_store(db: Session, tenant_id: UUID, user_id: UUID, *, name: str, engine: str,
                       connection_config: dict[str, Any]) -> GraphStoreRecord:
    require_membership(db, tenant_id, user_id, roles=ADMIN_ROLES)
    if engine == 'builtin':
        raise ValueError('the builtin graph store is always available and cannot be registered')
    capabilities.require_available('graph_store', engine)
    store_id, now = new_id(), utc_now()
    check_store('graph', engine, connection_config)
    sealed = seal_config(store_id, connection_config)
    row = GraphStoreRecord(id=store_id, tenant_id=tenant_id, name=_validate_name(name), engine=engine,
                           connection_config=sealed, created_by=user_id, created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    audit(db, tenant_id, user_id, 'graph_store.created', 'graph_store', str(row.id), {'engine': engine})
    return row


def delete_graph_store(db: Session, tenant_id: UUID, user_id: UUID, store_id: UUID) -> None:
    require_membership(db, tenant_id, user_id, roles=ADMIN_ROLES)
    row = db.get(GraphStoreRecord, store_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound('Graph store not found')
    for kb in db.scalars(select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.tenant_id == tenant_id,
                                                           KnowledgeBaseRecord.status == 'active')):
        if (kb.settings or {}).get('graph', {}).get('store') == str(store_id):
            raise Conflict('Graph store is used by a knowledge base')
    db.delete(row)
    audit(db, tenant_id, user_id, 'graph_store.deleted', 'graph_store', str(store_id), {})


capabilities.mark_available('kb_feature', 'vector_store_registry')
capabilities.mark_available('kb_feature', 'storage_backend_registry')
