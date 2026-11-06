"""Vector store port and engines (openspec 2026-11-06-knowledge-base K1, decision 1).

Importing this package registers the engines whose code is installed. ``sqlite`` is tested; ``postgres``,
``qdrant``, ``elasticsearch`` and ``milvus`` are implemented without a real environment and register with
``verified=False`` until they pass the real-environment acceptance.
"""
from .base import (FACTORIES, IndexRow, Scope, VectorIndex, VectorStoreError, collection_name, open_index,
                   register_engine)
from . import sqlite  # noqa: F401  (registers the engines)
from . import elasticsearch, milvus, postgres, qdrant  # noqa: F401,E401

__all__ = ['FACTORIES', 'IndexRow', 'Scope', 'VectorIndex', 'VectorStoreError', 'collection_name', 'open_index',
           'register_engine']
