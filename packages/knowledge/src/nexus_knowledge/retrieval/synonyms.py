"""Synonym groups for the keyword channel (FastGPT ``dataset/synonym``; openspec 2026-11-06-knowledge-base K5).

A knowledge base keeps groups of equivalent terms (``["退货", "退款", "返还"]``). When a query contains any term of a
group, the other terms are added to the keyword query, so a document that says "退款" matches a question that says
"退货". Only the keyword channel is expanded; the vector channel already generalizes. Expansion is bounded
(:data:`MAX_EXTRA`) and matching is case-insensitive substring on normalized text.
"""
from __future__ import annotations

from typing import Any, Sequence

MAX_GROUPS = 200
MAX_TERMS = 10
MAX_TERM_LEN = 50
MAX_EXTRA = 12


def parse(raw: Any) -> list[list[str]]:
    """Validated groups from settings; raises ``ValueError`` for malformed input."""
    if raw in (None, ''):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_GROUPS:
        raise ValueError(f'synonyms must be a list of at most {MAX_GROUPS} groups')
    groups: list[list[str]] = []
    for group in raw:
        if not isinstance(group, list):
            raise ValueError('each synonym group must be a list of terms')
        terms = list(dict.fromkeys(' '.join(str(t).split())[:MAX_TERM_LEN] for t in group if str(t).strip()))
        if len(terms) > MAX_TERMS:
            raise ValueError(f'a synonym group has at most {MAX_TERMS} terms')
        if len(terms) >= 2:
            groups.append(terms)
    return groups


def expand(query: str, groups: Sequence[Sequence[str]]) -> list[str]:
    """Terms to add to ``query``: the other members of every group that has a member in the query."""
    folded = (query or '').casefold()
    extra: list[str] = []
    for group in groups:
        if any(term.casefold() in folded for term in group):
            extra += [term for term in group if term.casefold() not in folded and term not in extra]
        if len(extra) >= MAX_EXTRA:
            break
    return extra[:MAX_EXTRA]
