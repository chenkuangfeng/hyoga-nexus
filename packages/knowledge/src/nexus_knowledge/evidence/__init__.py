"""Evidence registry and citation checking (openspec 2026-11-06-knowledge-base K1, decision 7)."""
from .registry import EvidenceRegistry, extract_handles, resolve_citations

__all__ = ['EvidenceRegistry', 'extract_handles', 'resolve_citations']
