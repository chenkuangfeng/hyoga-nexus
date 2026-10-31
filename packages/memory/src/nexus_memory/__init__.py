"""Reviewed, versioned memory: navigation index, published entries and drafts.

This package holds the memory rules (validation, review, versioning, bounded index).
It does not touch a database: callers supply a `MemoryRepository` (see `ports.py`)
and manage the transaction. The PostgreSQL adapter lives in `nexus_platform.memory`.
"""
