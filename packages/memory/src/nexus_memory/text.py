"""Pure text helpers for memory: CJK bigram tokens, sensitive-content redaction and fingerprints.

No database or platform imports. The same tokens are stored with each published version and
used by both the SQLite FTS5 index and the portable LIKE fallback, so the two backends match
the same words. Redaction runs before anything is stored; threat screening rejects a proposal.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

REDACTED = '【已隐藏】'

_CJK = r'一-鿿'
_WORD = re.compile(rf'[{_CJK}]+|[A-Za-z0-9_]+')


def tokenize(text: str) -> str:
    """Space-joined tokens: CJK runs become overlapping bigrams (single characters stay single),
    other runs are lowercased words. Quotes and operators never survive, so the result is safe to
    quote in an FTS5 query."""
    out: list[str] = []
    for run in _WORD.findall(text or ''):
        if run[0].isascii():
            out.append(run.lower())
        elif len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return ' '.join(out)


def query_tokens(query: str) -> list[str]:
    """Tokens of a search query, de-duplicated in order."""
    seen: dict[str, None] = {}
    for token in tokenize(query).split():
        seen.setdefault(token, None)
    return list(seen)


def is_single_cjk(token: str) -> bool:
    """A single CJK character is not indexed as part of a bigram; callers fall back to substring match."""
    return len(token) == 1 and not token.isascii()


def fingerprint(text: str) -> str:
    """Stable identity of memory content: whitespace-collapsed, case-folded, SHA-256 hex."""
    normalized = re.sub(r'\s+', ' ', (text or '').strip()).casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()


@dataclass(frozen=True)
class Screening:
    """Result of screening a proposed memory text.

    `threats` lists rule names that block the proposal; `redacted` lists the sensitive categories
    that were replaced. Only category names leave this module, never the matched text.
    """
    text: str
    threats: tuple[str, ...] = ()
    redacted: tuple[str, ...] = ()
    categories: dict[str, int] = field(default_factory=dict)


# Prompt-injection and exfiltration phrases. A proposal that matches is rejected, not redacted:
# silently keeping a fragment of an instruction would still store it.
_THREAT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('prompt_override', re.compile(
        r'(?i)ignore\s+(?:all\s+|the\s+)?(?:previous|above|prior)\s+(?:instructions|rules|prompts?)'
        r'|忽略(?:以上|之前|前面|所有|上述)(?:的)?(?:指令|指示|规则|提示)')),
    ('role_hijack', re.compile(r'(?i)you\s+are\s+now\s+|从现在起你是|你现在是')),
    ('prompt_leak', re.compile(r'(?i)system\s+prompt|系统提示词')),
    ('reserved_markup', re.compile(r'(?i)</?\s*(?:system|user_memory)\b')),
    ('exfiltration', re.compile(r'(?i)(?:curl|wget)\s+\S+[^\n]*\$\w+|send\s+(?:all\s+)?(?:the\s+)?(?:keys|secrets|passwords)')),
    ('invisible_chars', re.compile('[​-‏‪-‮⁠-⁤﻿]')),
)

_PEM = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.S)
_PREFIXED = [
    ('openai_key', re.compile(r'\bsk-[A-Za-z0-9_\-]{16,}')),
    ('aws_access_key', re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b')),
    ('github_token', re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b')),
    ('slack_token', re.compile(r'\bxox[abprs]-[A-Za-z0-9\-]{10,}')),
    ('bearer_token', re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}')),
]
_KEY_VALUE = re.compile(r'(?i)\b((?:api[_\-]?key|apikey|password|passwd|secret|client[_\-]?secret|token|access[_\-]?token)'
                        r'\s*[:=]\s*)(\S+)')
_CN_ID = re.compile(r'(?<![0-9A-Za-z])\d{17}[0-9Xx](?![0-9A-Za-z])')
_CARD = re.compile(r'(?<![0-9])\d{13,19}(?![0-9])')
_CN_MOBILE = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _cn_id_valid(candidate: str) -> bool:
    """Checksum of the 18-digit resident ID number (ISO 7064 MOD 11-2)."""
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    codes = '10X98765432'
    total = sum(int(c) * w for c, w in zip(candidate[:17], weights))
    return codes[total % 11] == candidate[17].upper()


def screen(text: str) -> Screening:
    """Reject threats and redact sensitive values. Pure: returns a new text and category counts.

    Redaction order matters: PEM blocks and prefixed tokens first, then key=value pairs, then
    numeric identifiers (ID numbers and card numbers are validated by checksum, so ordinary numbers
    are not replaced).
    """
    threats = tuple(name for name, pattern in _THREAT_RULES if pattern.search(text or ''))
    if threats:
        return Screening(text=text, threats=threats)

    categories: dict[str, int] = {}

    def swap(pattern: re.Pattern[str], category: str, value: str, check=None) -> str:
        def repl(match: re.Match[str]) -> str:
            if check is not None and not check(match.group(0)):
                return match.group(0)
            categories[category] = categories.get(category, 0) + 1
            return REDACTED
        return pattern.sub(repl, value)

    out = swap(_PEM, 'private_key', text or '')
    for category, pattern in _PREFIXED:
        out = swap(pattern, category, out)
    # Key=value keeps the key name so the reader still sees what was hidden.
    def kv(match: re.Match[str]) -> str:
        categories['credential_assignment'] = categories.get('credential_assignment', 0) + 1
        return match.group(1) + REDACTED
    out = _KEY_VALUE.sub(kv, out)
    out = swap(_CN_ID, 'cn_resident_id', out, _cn_id_valid)
    out = swap(_CARD, 'bank_card', out, _luhn)
    out = swap(_CN_MOBILE, 'cn_mobile', out)
    return Screening(text=out, redacted=tuple(sorted(categories)), categories=categories)
