"""FAQ domain rules (openspec 2026-11-06-knowledge-base K3; WeKnora ``types/faq.go``, ``knowledge_faq_import.go``).

An entry has a standard question, similar questions (also match), negative questions (a query that matches one
must not return this entry), answers and an answer strategy. This module is pure: normalization, conflict rules,
the texts that get indexed, negative-question filtering and the CSV import/export format.

Conflict rules (WeKnora import dry run):
- the standard question is unique in a base; a duplicate is *blocked*;
- a similar question equal to another entry's standard or similar question is *removed* (it would make two
  entries answer the same question);
- a negative question equal to the entry's own standard or similar question is *removed*.
"""
from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

MAX_QUESTION = 1000
MAX_ANSWER = 8000
MAX_SIMILAR = 50
MAX_NEGATIVE = 50
MAX_ANSWERS = 10
STRATEGIES = ('all', 'first')
INDEX_MODES = ('question_only', 'question_answer')
QUESTION_MODES = ('combined', 'separate')
SEPARATOR = '##'
NEGATIVE_MATCH = 0.85


def key(text: str) -> str:
    """Identity of a question: NFKC, case-folded, whitespace and punctuation removed."""
    folded = unicodedata.normalize('NFKC', text or '').casefold()
    return ''.join(ch for ch in folded if ch.isalnum())[:255]


def clean_list(values: Iterable[Any] | None, limit: int, size: int) -> list[str]:
    """Trimmed, de-duplicated (by :func:`key` for questions would over-merge answers, so by exact text)."""
    out: list[str] = []
    for value in values or ():
        text = ' '.join(str(value or '').split()) if size == MAX_QUESTION else str(value or '').strip()
        text = text[:size]
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


@dataclass
class FaqInput:
    standard_question: str
    answers: list[str]
    similar_questions: list[str] = field(default_factory=list)
    negative_questions: list[str] = field(default_factory=list)
    category: str = ''
    answer_strategy: str = 'all'
    enabled: bool = True
    recommended: bool = False


def normalize(raw: Mapping[str, Any]) -> FaqInput:
    """Validated entry from a request or CSV row; raises ``ValueError`` with a user-facing reason."""
    question = ' '.join(str(raw.get('standard_question') or '').split())[:MAX_QUESTION]
    if not question:
        raise ValueError('标准问不能为空')
    answers = clean_list(raw.get('answers'), MAX_ANSWERS, MAX_ANSWER)
    if not answers:
        raise ValueError('答案不能为空')
    strategy = str(raw.get('answer_strategy') or 'all')
    if strategy not in STRATEGIES:
        raise ValueError(f'answer_strategy must be one of {", ".join(STRATEGIES)}')
    return FaqInput(
        question, answers,
        [q for q in clean_list(raw.get('similar_questions'), MAX_SIMILAR, MAX_QUESTION) if key(q) != key(question)],
        clean_list(raw.get('negative_questions'), MAX_NEGATIVE, MAX_QUESTION),
        ' '.join(str(raw.get('category') or raw.get('tag_name') or '').split())[:160], strategy,
        raw.get('is_enabled', raw.get('enabled', True)) is not False, bool(raw.get('is_recommended', raw.get('recommended', False))))


@dataclass
class Resolved:
    entry: FaqInput | None
    reason: str = ''
    notes: list[str] = field(default_factory=list)


def resolve(entry: FaqInput, taken_standard: Mapping[str, str], taken_similar: Mapping[str, str],
            own_id: str | None = None) -> Resolved:
    """Apply the conflict rules against the base's other entries.

    ``taken_standard`` / ``taken_similar`` map question keys to the owning entry id; ``own_id`` excludes the
    entry itself when it is being edited.
    """
    notes: list[str] = []
    owner = taken_standard.get(key(entry.standard_question))
    if owner is not None and owner != own_id:
        return Resolved(None, f'标准问重复：「{entry.standard_question}」已存在')
    owner = taken_similar.get(key(entry.standard_question))
    if owner is not None and owner != own_id:
        return Resolved(None, f'标准问「{entry.standard_question}」与其他条目的相似问重复')
    similar = []
    for question in entry.similar_questions:
        owner = taken_standard.get(key(question)) or taken_similar.get(key(question))
        if owner is not None and owner != own_id:
            notes.append(f'相似问「{question}」与其他条目冲突，已移除')
            continue
        similar.append(question)
    own = {key(entry.standard_question), *(key(q) for q in similar)}
    negative = []
    for question in entry.negative_questions:
        if key(question) in own:
            notes.append(f'反例「{question}」与本条目的问题相同，已移除')
            continue
        negative.append(question)
    return Resolved(FaqInput(entry.standard_question, entry.answers, similar, negative, entry.category,
                             entry.answer_strategy, entry.enabled, entry.recommended), notes=notes)


def index_texts(question: str, similar: Sequence[str], answers: Sequence[str], index_mode: str,
                question_mode: str) -> list[str]:
    """Texts to index for one entry (one index row each).

    ``question_only`` indexes questions only; ``question_answer`` adds the answers to every row. ``combined``
    puts the standard and similar questions into a single row, ``separate`` gives each question its own row.
    """
    questions = [question, *similar]
    tail = ('\n' + '\n'.join(answers)) if index_mode == 'question_answer' else ''
    if question_mode == 'separate':
        return [q + tail for q in questions]
    return ['\n'.join(questions) + tail]


def _bigrams(text: str) -> set[str]:
    folded = key(text)
    return {folded[i:i + 2] for i in range(len(folded) - 1)} or {folded}


def similarity(a: str, b: str) -> float:
    left, right = _bigrams(a), _bigrams(b)
    return len(left & right) / len(left | right) if left and right else 0.0


def negated(query: str, negative_questions: Sequence[str]) -> bool:
    """True when ``query`` is (almost) one of the entry's negative questions."""
    return any(key(query) == key(n) or similarity(query, n) >= NEGATIVE_MATCH for n in negative_questions)


def answer_text(answers: Sequence[str], strategy: str) -> str:
    return (answers[0] if strategy == 'first' and answers else '\n\n'.join(answers))


# ---------------------------------------------------------------- CSV

HEADERS = ('分类', '问题', '相似问题', '反例问题', '机器人回答', '是否全部回复', '是否停用')
_ALIASES = {
    'category': ('分类', '分类(必填)', 'category', 'tag', 'tag_name'),
    'standard_question': ('问题', '问题(必填)', 'standard_question', 'question'),
    'similar_questions': ('相似问题', '相似问题(选填-多个用##分隔)', 'similar_questions'),
    'negative_questions': ('反例问题', '反例问题(选填-多个用##分隔)', 'negative_questions'),
    'answers': ('机器人回答', '机器人回答(必填-多个用##分隔)', 'answers', 'answer'),
    'all_answers': ('是否全部回复', '是否全部回复(选填-默认FALSE)', 'answer_strategy'),
    'disabled': ('是否停用', '是否停用(选填-默认FALSE)', 'is_disabled'),
}


def _truthy(value: str) -> bool:
    return str(value or '').strip().casefold() in {'1', 'true', 'yes', 'y', '是', '真'}


def _split(value: str) -> list[str]:
    return [part for part in (value or '').split(SEPARATOR) if part.strip()]


def parse_csv(data: bytes) -> list[dict[str, Any]]:
    """Rows of a WeKnora-format FAQ CSV as entry dicts. UTF-8 (BOM allowed) or GB18030."""
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('文件编码无法识别')
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    header = [h.strip().casefold() for h in rows[0]]
    columns: dict[str, int] = {}
    for field_name, names in _ALIASES.items():
        for name in names:
            if name.casefold() in header:
                columns[field_name] = header.index(name.casefold())
                break
    if 'standard_question' not in columns or 'answers' not in columns:
        raise ValueError('缺少「问题」或「机器人回答」列')

    def cell(row: list[str], name: str) -> str:
        index = columns.get(name)
        return row[index].strip() if index is not None and index < len(row) else ''

    out = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        out.append({
            'category': cell(row, 'category'), 'standard_question': cell(row, 'standard_question'),
            'similar_questions': _split(cell(row, 'similar_questions')),
            'negative_questions': _split(cell(row, 'negative_questions')), 'answers': _split(cell(row, 'answers')),
            'answer_strategy': 'all' if _truthy(cell(row, 'all_answers')) else 'first'
            if 'all_answers' in columns else 'all',
            'is_enabled': not _truthy(cell(row, 'disabled'))})
    return out


def to_csv(entries: Iterable[Mapping[str, Any]]) -> bytes:
    """CSV with the same columns as the import template (UTF-8 with BOM, opens correctly in Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADERS)
    for entry in entries:
        writer.writerow([entry.get('category', ''), entry['standard_question'],
                         SEPARATOR.join(entry.get('similar_questions') or []),
                         SEPARATOR.join(entry.get('negative_questions') or []),
                         SEPARATOR.join(entry.get('answers') or []),
                         'TRUE' if entry.get('answer_strategy', 'all') == 'all' else 'FALSE',
                         'FALSE' if entry.get('enabled', True) else 'TRUE'])
    return ('﻿' + buffer.getvalue()).encode('utf-8')
