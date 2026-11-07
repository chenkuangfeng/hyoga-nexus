"""Advisory lint for a skill being written (openspec 2026-11-07-skill-evolution, S4 4.7).

Never blocks anything: at most three short notes come back with a draft edit so the author (usually the model) can
tighten the skill. Rules follow what the reference projects found makes skills work badly: a long description that
crowds the index, a long body that costs tokens on every load, filler words, shouting, and changelog narration.
"""
from __future__ import annotations

import re

DESCRIPTION_BYTES = 160
BODY_LINES = 250
BODY_BYTES = 12 * 1024
MAX_NOTES = 3
_FILLER = re.compile(r'\b(comprehensive|robust|powerful|seamless(?:ly)?|cutting[- ]edge|state[- ]of[- ]the[- ]art|'
                     r'best[- ]in[- ]class|leverage[sd]?|utili[sz]e[sd]?)\b|全面的|强大的|无缝|最先进|赋能', re.IGNORECASE)
_SHOUTING = re.compile(r'\b(?:MUST|NEVER|ALWAYS|IMPORTANT|CRITICAL|DO NOT)\b')
_CHANGELOG = re.compile(r'^\s*(?:#+\s*)?(?:changelog|change log|更新记录|更新日志|v\d+(?:\.\d+)*\s*[:：-])', re.IGNORECASE | re.MULTILINE)


def lint(description: str, body: str) -> list[str]:
    """Up to three advisory notes, most useful first. Empty when the skill is in good shape."""
    notes: list[str] = []
    if len(description.encode('utf-8')) > DESCRIPTION_BYTES:
        notes.append(f'description_long: keep the description under {DESCRIPTION_BYTES} bytes; it is shown for every skill on every turn')
    lines = body.count('\n') + 1
    if lines > BODY_LINES or len(body.encode('utf-8')) > BODY_BYTES:
        notes.append(f'body_long: the body is {lines} lines; move detail into refs/ files and read them on demand')
    if _FILLER.search(description) or _FILLER.search(body):
        notes.append('filler_words: drop adjectives such as "comprehensive" or "powerful"; state what the skill does')
    if len(_SHOUTING.findall(body)) >= 3:
        notes.append('shouting: replace repeated MUST / NEVER / ALWAYS with one reason the model can follow')
    if _CHANGELOG.search(body):
        notes.append('changelog: version history does not belong in the instructions; the platform keeps versions')
    return notes[:MAX_NOTES]
