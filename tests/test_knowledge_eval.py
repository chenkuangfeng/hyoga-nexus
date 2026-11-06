"""Knowledge evaluation gate on SQLite keyword retrieval (evals/knowledge)."""
import asyncio
import sys
from pathlib import Path

import pytest

from nexus_core.platform import Principal
from nexus_knowledge.evidence import EvidenceRegistry, resolve_citations
from nexus_platform.identity.service import resolve_user
from nexus_platform.knowledge import search, service
from nexus_platform.tenants.service import create_tenant

from test_knowledge_service import drain, upload
from test_platform import database  # noqa: F401 (pytest fixture)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'evals' / 'knowledge'))
import corpus  # noqa: E402


def test_keyword_retrieval_meets_the_gate(database, deployment_config, tmp_path):
    deployment_config(f'[knowledge]\ndata_dir = "{tmp_path / "k"}"\n')
    owner_a, owner_b = Principal('eval-a', 'test'), Principal('eval-b', 'test')
    with database() as db:
        space_a = create_tenant(db, owner_a, 'A')
        space_b = create_tenant(db, owner_b, 'B')
    with database() as db:
        user_a, user_b = resolve_user(db, owner_a).id, resolve_user(db, owner_b).id
        db.commit()
    kinds = {'indexing': {'vector': False, 'keyword': True}}
    with database() as db, db.begin():
        kb_a = service.create_base(db, space_a.id, user_a, name='语料', **kinds).id
        kb_b = service.create_base(db, space_b.id, user_b, name='机密', **kinds).id
    for name, text in corpus.CORPUS_A.items():
        upload(database, space_a.id, user_a, kb_a, name, text.encode())
    for name, text in corpus.CORPUS_B.items():
        upload(database, space_b.id, user_b, kb_b, name, text.encode())
    drain(database)

    def find(query):
        with database() as db:
            return asyncio.run(search.search(database, db, space_a.id, user_a, query, limit=3))

    hits = sum(any(h.filename == q.expect for h in find(q.query).hits) for q in corpus.QUESTIONS)
    assert hits / len(corpus.QUESTIONS) >= 0.85, hits
    leaks = sum(h.kb_id == str(kb_b) for probe in corpus.LEAK_PROBES for h in find(probe).hits)
    assert leaks == 0
    # Every handle the answer cites resolves; an invented one is counted invalid.
    registry = EvidenceRegistry()
    first = find(corpus.QUESTIONS[0].query).hits[0]
    handle, _ = registry.serve(first.chunk_id, first.content, first.ref())
    citations, invalid = resolve_citations(f'七天内可退 [ID:{handle}]', registry)
    assert len(citations) == 1 and invalid == []
