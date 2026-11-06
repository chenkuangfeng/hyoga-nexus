"""FAQ domain rules (K3)."""
import pytest

from nexus_knowledge import faq


def entry(**kw):
    base = {'standard_question': '如何修改密码？', 'answers': ['在设置中修改']}
    return faq.normalize({**base, **kw})


def test_normalize_cleans_and_validates():
    e = entry(similar_questions=['怎么改密码', ' 怎么改密码 ', '如何修改密码?', ''], answers=['a', 'a', ' b '],
              negative_questions=['忘记密码怎么办'], category='账号', tag_name='x')
    assert e.similar_questions == ['怎么改密码']  # '如何修改密码?' equals the standard question and is dropped
    assert e.answers == ['a', 'b'] and e.category == '账号' and e.enabled
    with pytest.raises(ValueError):
        faq.normalize({'standard_question': '', 'answers': ['x']})
    with pytest.raises(ValueError):
        faq.normalize({'standard_question': 'q', 'answers': []})
    with pytest.raises(ValueError):
        faq.normalize({'standard_question': 'q', 'answers': ['a'], 'answer_strategy': 'random'})


def test_conflict_rules():
    taken_standard = {faq.key('如何联系客服'): 'e1'}
    taken_similar = {faq.key('客服电话'): 'e1'}
    blocked = faq.resolve(entry(standard_question='如何联系客服!'), taken_standard, taken_similar)
    assert blocked.entry is None and '重复' in blocked.reason
    blocked = faq.resolve(entry(standard_question='客服电话'), taken_standard, taken_similar)
    assert blocked.entry is None
    ok = faq.resolve(entry(similar_questions=['客服电话', '怎么改密码'], negative_questions=['如何修改密码', '重置密码']),
                     taken_standard, taken_similar)
    assert ok.entry.similar_questions == ['怎么改密码'] and ok.entry.negative_questions == ['重置密码']
    assert len(ok.notes) == 2
    # Editing the owner itself is not a conflict.
    assert faq.resolve(entry(standard_question='如何联系客服'), taken_standard, taken_similar, own_id='e1').entry


def test_index_texts_follow_the_modes():
    args = ('Q', ['S1', 'S2'], ['A1', 'A2'])
    assert faq.index_texts(*args, 'question_only', 'combined') == ['Q\nS1\nS2']
    assert faq.index_texts(*args, 'question_only', 'separate') == ['Q', 'S1', 'S2']
    assert faq.index_texts(*args, 'question_answer', 'separate') == ['Q\nA1\nA2', 'S1\nA1\nA2', 'S2\nA1\nA2']
    assert faq.index_texts(*args, 'question_answer', 'combined') == ['Q\nS1\nS2\nA1\nA2']


def test_negative_questions_filter_close_queries_only():
    assert faq.negated('忘记密码怎么办？', ['忘记密码怎么办'])
    assert faq.negated('忘记 密码 怎么办', ['忘记密码怎么办'])
    assert not faq.negated('如何修改密码', ['忘记密码怎么办'])
    assert faq.answer_text(['a', 'b'], 'first') == 'a' and faq.answer_text(['a', 'b'], 'all') == 'a\n\nb'


def test_csv_round_trip_in_the_weknora_format():
    csv_bytes = ('分类,问题,相似问题,反例问题,机器人回答,是否全部回复,是否停用\n'
                 '账号,如何改密码,怎么改密码##密码修改,忘记密码,在设置修改##或联系客服,TRUE,FALSE\n'
                 ',,,,,,\n'
                 '账号,停用的问题,,,答案,FALSE,TRUE\n').encode('utf-8-sig')
    rows = faq.parse_csv(csv_bytes)
    assert len(rows) == 2
    assert rows[0]['similar_questions'] == ['怎么改密码', '密码修改'] and rows[0]['answers'] == ['在设置修改', '或联系客服']
    assert rows[0]['answer_strategy'] == 'all' and rows[0]['is_enabled'] is True
    assert rows[1]['is_enabled'] is False and rows[1]['answer_strategy'] == 'first'
    exported = faq.to_csv([{**faq.normalize(r).__dict__} for r in rows])
    assert faq.parse_csv(exported)[0]['standard_question'] == '如何改密码'
    with pytest.raises(ValueError):
        faq.parse_csv('a,b\n1,2'.encode())
    assert faq.parse_csv('问题,机器人回答\nq,a'.encode('gb18030'))[0]['answers'] == ['a']
