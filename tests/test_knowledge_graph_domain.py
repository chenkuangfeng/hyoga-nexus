"""Knowledge graph domain: extraction parsing, conservative merge, communities, bounded expansion (K2)."""
import json

from nexus_knowledge.graph import community, extract, merge, retrieve
from nexus_knowledge.graph.merge import Source


def _reply(entities, relations):
    return json.dumps({'entities': entities, 'relations': relations}, ensure_ascii=False)


def test_extraction_parsing_drops_malformed_and_unknown_relations():
    raw = '```json\n' + _reply(
        [{'name': '甲公司', 'type': '组织', 'description': '一家公司'}, {'name': '乙产品', 'type': '产品'},
         {'name': '', 'type': 'x'}, 'bad', {'name': '甲公司', 'type': '组织'}],
        [{'source': '甲公司', 'target': '乙产品', 'description': '生产', 'keywords': ['生产', '生产'], 'weight': 99},
         {'source': '甲公司', 'target': '不存在', 'description': 'x'},
         {'source': '甲公司', 'target': '甲公司', 'description': '自环'}]) + '\n```'
    result = extract.parse_extraction(raw)
    assert [e.name for e in result.entities] == ['甲公司', '乙产品']
    assert len(result.relations) == 1
    relation = result.relations[0]
    assert (relation.source, relation.target, relation.keywords, relation.weight) == ('甲公司', '乙产品', ('生产',), 10.0)
    assert extract.parse_extraction('not json').entities == []
    assert extract.parse_extraction('[1]').entities == []


def test_entity_types_outside_the_schema_are_cleared():
    schema = extract.Schema(entity_types=('组织',))
    result = extract.parse_extraction(_reply([{'name': '甲', 'type': '组织'}, {'name': '乙', 'type': '地点'}], []), schema)
    assert [(e.name, e.type) for e in result.entities] == [('甲', '组织'), ('乙', '')]


def test_cache_key_changes_with_text_schema_model_and_mode():
    base = extract.cache_key('文本', extract.Schema(), 'm1', 'graphrag_light')
    assert base == extract.cache_key('文本', extract.Schema(), 'm1', 'graphrag_light')
    assert len({base, extract.cache_key('别的', extract.Schema(), 'm1', 'graphrag_light'),
                extract.cache_key('文本', extract.Schema(entity_types=('x',)), 'm1', 'graphrag_light'),
                extract.cache_key('文本', extract.Schema(), 'm2', 'graphrag_light'),
                extract.cache_key('文本', extract.Schema(), 'm1', 'entity')}) == 5


def _x(entities, relations=()):
    return extract.parse_extraction(_reply(entities, list(relations)))


def test_merge_joins_untyped_mentions_to_the_single_typed_entity():
    graph = merge.merge([
        (Source('c1', 'v1'), _x([{'name': '苹果', 'type': '公司', 'description': '科技公司'}, {'name': '库克', 'type': '人物'}],
                                [{'source': '库克', 'target': '苹果', 'description': '担任 CEO', 'weight': 4}])),
        (Source('c2', 'v1'), _x([{'name': '苹　果', 'type': '', 'description': '总部在库比蒂诺'}, {'name': '库克', 'type': '人物'}],
                                [{'source': '苹果', 'target': '库克', 'description': '领导', 'weight': 3}])),
        (Source('c4', 'v2'), _x([{'name': '苹果公司', 'type': '公司'}])),
    ])
    names = sorted((e.name, e.type) for e in graph.entities.values())
    # Similar names ('苹果' vs '苹果公司') are never merged.
    assert names == [('库克', '人物'), ('苹果', '公司'), ('苹果公司', '公司')]
    company = next(e for e in graph.entities.values() if e.name == '苹果')
    assert '总部在库比蒂诺' in company.description and {s.chunk_id for s in company.sources} == {'c1', 'c2'}
    [relation] = graph.relations.values()
    assert relation.weight == 7.0 and '担任 CEO' in relation.description and '领导' in relation.description
    assert company.degree == 1


def test_same_name_with_different_types_stays_separate_and_untyped_mentions_are_not_guessed():
    graph = merge.merge([
        (Source('c1', 'v1'), _x([{'name': '苹果', 'type': '公司'}])),
        (Source('c2', 'v1'), _x([{'name': '苹果', 'type': '水果'}])),
        (Source('c3', 'v1'), _x([{'name': '苹果', 'type': ''}])),
    ])
    assert sorted((e.name, e.type) for e in graph.entities.values()) == [('苹果', ''), ('苹果', '公司'), ('苹果', '水果')]


def test_merge_is_deterministic():
    inputs = [(Source('c1', 'v'), _x([{'name': 'A', 'type': 't'}, {'name': 'B', 'type': 't'}],
                                     [{'source': 'A', 'target': 'B', 'description': 'd'}]))]
    assert merge.merge(inputs) == merge.merge(inputs)


def _clusters():
    items = []
    for prefix in ('甲', '乙'):
        names = [f'{prefix}{i}' for i in range(5)]
        rels = [{'source': names[i], 'target': names[j], 'description': 'r', 'weight': 5}
                for i in range(5) for j in range(i + 1, 5)]
        items.append((Source(prefix, 'v'), _x([{'name': n, 'type': 't'} for n in names], rels)))
    items.append((Source('x', 'v'), _x([{'name': '甲0'}, {'name': '乙0'}],
                                       [{'source': '甲0', 'target': '乙0', 'description': 'bridge', 'weight': 1}])))
    return merge.merge(items)


def test_communities_split_two_dense_clusters_and_reports_are_bounded():
    graph = _clusters()
    found = community.detect(graph)
    top = [c for c in found if c.level == min(c2.level for c2 in found)]
    assert sorted(len(c.members) for c in top) == [5, 5]
    assert community.detect(graph) == found  # deterministic
    message = community.build_report_message(graph, top[0])
    assert message.startswith('<entities>') and '<relations>' in message
    assert community.parse_report('{"title":"T","summary":"S"}') == ('T', 'S')
    assert community.parse_report('oops') == ('', '')
    assert community.detect(merge.Graph()) == []


def test_expansion_is_bounded_and_reports_truncation():
    edges = {'a': [('r1', 'b', 5), ('r2', 'c', 1)], 'b': [('r1', 'a', 5), ('r3', 'd', 3)], 'c': [('r2', 'a', 1)],
             'd': [('r3', 'b', 3)]}
    full = retrieve.expand(['a'], edges, retrieve.Limits(hops=3, max_entities=10, max_relations=10))
    assert full.entity_ids == ['a', 'b', 'c', 'd'] and not full.truncated
    one_hop = retrieve.expand(['a'], edges, retrieve.Limits(hops=1))
    assert one_hop.entity_ids == ['a', 'b', 'c'] and one_hop.truncated  # b still has an unexplored relation
    capped = retrieve.expand(['a'], edges, retrieve.Limits(hops=3, max_entities=2, max_relations=10))
    assert capped.entity_ids == ['a', 'b'] and capped.truncated
    kept, cut = retrieve.fit(['aaaa', 'bbbb', 'cccc'], 9)
    assert kept == ['aaaa', 'bbbb'] and cut
