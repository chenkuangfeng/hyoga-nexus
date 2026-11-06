"""Original-file storage backends (openspec 2026-11-06-knowledge-base K1)."""
from .blob import BlobStore, BlobStoreError, LocalBlobStore, open_blob_store

__all__ = ['BlobStore', 'BlobStoreError', 'LocalBlobStore', 'open_blob_store']
