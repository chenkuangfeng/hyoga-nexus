"""Keyword tokens for the knowledge keyword channel.

CJK runs become overlapping bigrams and other runs lowercase words, the same rule as
``nexus_memory.text.tokenize`` (kept as a copy so this package depends on ``nexus_core`` only). Every
keyword index (SQLite FTS5, PostgreSQL ``tsvector('simple')``, Elasticsearch whitespace analyzer, Milvus
and Qdrant sparse terms) indexes these tokens, so all engines match the same words without a Chinese
segmenter. Reference: WeKnora ``retriever/sqlite`` ``tokenizeCJKBigram``.
"""
from __future__ import annotations

import re

_CJK = r'一-鿿㐀-䶿'
_WORD = re.compile(rf'[{_CJK}]+|[A-Za-z0-9_]+')


def tokenize(text: str) -> str:
    """Space-joined tokens. Quotes and operators never survive, so the result is safe in FTS queries."""
    out: list[str] = []
    for run in _WORD.findall(text or ''):
        if run[0].isascii():
            out.append(run.lower())
        elif len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return ' '.join(out)


def query_tokens(query: str, limit: int = 32) -> list[str]:
    """De-duplicated tokens of a query, in order, at most ``limit`` (long queries keep their start)."""
    seen: dict[str, None] = {}
    for token in tokenize(query).split():
        seen.setdefault(token, None)
        if len(seen) >= limit:
            break
    return list(seen)
