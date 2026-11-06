"""Connection and index form fields per vector engine (openspec 2026-11-06-knowledge-base K1.6).

The settings page renders the "new vector store" form from these schemas (WeKnora ``FieldSchema``:
``name``, ``type``, ``required``, ``sensitive``, ``description``, ``default``). Engines without a schema
are planned and listed with empty fields. Sensitive fields are encrypted at rest and masked in listings.
"""
from __future__ import annotations

from typing import Any


def _field(name: str, kind: str = 'string', *, required: bool = False, sensitive: bool = False,
           description: str = '', default: Any = None, minimum: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {'name': name, 'type': kind, 'required': required, 'sensitive': sensitive,
                           'description': description}
    if default is not None:
        out['default'] = default
    if minimum is not None:
        out['min'] = minimum
    return out


CONNECTION_FIELDS: dict[str, list[dict[str, Any]]] = {
    'sqlite': [_field('path', required=True, description='SQLite 文件路径（相对部署目录）',
                      default='data/knowledge/vectors-custom.db')],
    'postgres': [_field('dsn', required=True, sensitive=True,
                        description='postgresql://user:password@host:5432/db（需已执行 CREATE EXTENSION vector）')],
    'qdrant': [_field('url', required=True, description='http://host:6333'),
               _field('api_key', sensitive=True), _field('verify_tls', 'boolean', default=True)],
    'elasticsearch': [_field('url', required=True, description='https://host:9200（Elasticsearch 8.x）'),
                      _field('username'), _field('password', sensitive=True), _field('api_key', sensitive=True),
                      _field('verify_tls', 'boolean', default=True)],
    'milvus': [_field('url', required=True, description='http://host:19530（Milvus 2.5+）'),
               _field('token', sensitive=True, description='user:password 或 API Key'),
               _field('database', default='default'), _field('verify_tls', 'boolean', default=True)],
}

INDEX_FIELDS: dict[str, list[dict[str, Any]]] = {
    'postgres': [_field('schema', default='public')],
    'qdrant': [_field('collection_prefix', default='nexus_'), _field('shard_number', 'number', default=1, minimum=1),
               _field('replication_factor', 'number', default=1, minimum=1)],
    'elasticsearch': [_field('index_prefix', default='nexus_'),
                      _field('number_of_shards', 'number', default=1, minimum=1),
                      _field('number_of_replicas', 'number', default=1, minimum=0)],
    'milvus': [_field('collection_prefix', default='nexus_'), _field('shards_num', 'number', default=1, minimum=1)],
}
