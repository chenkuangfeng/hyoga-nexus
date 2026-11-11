"""Document affinity: counting citations and boosting a person's favourite documents (memory evolution D5)."""
from uuid import uuid4

from nexus_core.platform import Principal
from nexus_platform.knowledge import service
from nexus_platform.memory import doc_affinity
from nexus_platform.persistence.models import MemorySpaceSettingsRecord

from test_knowledge_service import MEMBER, drain, env, find, upload  # noqa: F401 (pytest fixture)
from test_platform import database  # noqa: F401 (pytest fixture)


def test_factor_is_capped_and_starts_at_two_citations():
    assert doc_affinity.factor(0) == doc_affinity.factor(1) == 1.0
    assert 1.0 < doc_affinity.factor(2) < doc_affinity.factor(4) < doc_affinity.factor(8) == 1.15
    assert doc_affinity.factor(100) == 1.15


def test_favourite_document_is_boosted_only_for_its_reader(env):
    factory, tenant_id, _, owner, member, _ = env
    with factory() as db, db.begin():
        kb_id = service.create_base(db, tenant_id, owner, visibility='tenant', name='退货',
                                    indexing={'vector': False, 'keyword': True}).id
    first, _ = upload(factory, tenant_id, owner, kb_id, 'a.md', '# 退货\n退货流程说明，七天内可退。甲'.encode())
    second, _ = upload(factory, tenant_id, owner, kb_id, 'b.md', '# 退货\n退货流程说明，七天内可退。乙'.encode())
    drain(factory)
    base = [h.document_id for h in find(factory, tenant_id, member, '退货流程').hits]
    assert set(base) == {str(first), str(second)}
    favourite = base[1]  # the document that does not lead without affinity
    with factory() as db, db.begin():
        assert doc_affinity.record(db, tenant_id=tenant_id, owner_id=member, document_ids=[favourite, str(uuid4())]) == 1
    hits = find(factory, tenant_id, member, '退货流程').hits
    assert all('affinity' not in h.ranks for h in hits)  # one citation: no boost yet
    before = {h.document_id: h.score for h in hits}
    with factory() as db, db.begin():
        doc_affinity.record(db, tenant_id=tenant_id, owner_id=member, document_ids=[favourite])
    hits = find(factory, tenant_id, member, '退货流程').hits
    boosted = next(h for h in hits if h.document_id == favourite)
    assert boosted.ranks['affinity'] == doc_affinity.factor(2)
    assert boosted.score == round(before[favourite] * doc_affinity.factor(2), 6)  # small: it never reorders clear gaps
    assert [h.document_id for h in hits] == base
    # Another person's results are unchanged.
    other = find(factory, tenant_id, owner, '退货流程').hits
    assert all('affinity' not in h.ranks for h in other)
    # Switching memory off for the space stops the boost and the counting.
    from nexus_core.platform import utc_now
    with factory() as db, db.begin():
        db.add(MemorySpaceSettingsRecord(tenant_id=tenant_id, enabled=False, write_mode='auto', updated_by=owner,
                                         updated_at=utc_now()))
    assert all('affinity' not in h.ranks for h in find(factory, tenant_id, member, '退货流程').hits)
    with factory() as db, db.begin():
        assert doc_affinity.record(db, tenant_id=tenant_id, owner_id=member, document_ids=[favourite]) == 0


def test_owner_can_list_and_clear_counters(env):
    factory, tenant_id, _, owner, member, _ = env
    with factory() as db, db.begin():
        kb_id = service.create_base(db, tenant_id, owner, name='库', indexing={'vector': False, 'keyword': True}).id
    first, _ = upload(factory, tenant_id, owner, kb_id, 'a.md', '# a\n内容甲'.encode())
    second, _ = upload(factory, tenant_id, owner, kb_id, 'b.md', '# b\n内容乙'.encode())
    drain(factory)
    with factory() as db, db.begin():
        for _ in range(3):
            doc_affinity.record(db, tenant_id=tenant_id, owner_id=member, document_ids=[str(first), str(second)])
    member_principal = MEMBER
    with factory() as db:
        listed = doc_affinity.list_affinity(db, member_principal, tenant_id)
    assert {i['filename'] for i in listed} == {'a.md', 'b.md'} and listed[0]['hits'] == 3 and listed[0]['boost'] > 1.0
    with factory() as db:
        assert doc_affinity.clear(db, member_principal, tenant_id, first) == 1
    with factory() as db:
        assert [i['filename'] for i in doc_affinity.list_affinity(db, member_principal, tenant_id)] == ['b.md']
        assert doc_affinity.clear(db, member_principal, tenant_id) == 1
