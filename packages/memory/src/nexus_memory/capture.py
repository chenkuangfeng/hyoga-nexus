"""Pure rules for automatic memory capture (openspec 2026-11-01-memory-optimization, stage 3).

Capture reads a finished conversation and proposes memory drafts. Everything here is deterministic
and free of I/O so the cadence, backoff and output validation can be tested without a database or model.

Contract notes:
- Extraction output is untrusted. `validate_actions` keeps only well-formed actions and counts the rest;
  nothing is stored from a rejected action.
- Capture never publishes. Valid actions become drafts through `service.propose` with `origin='capture'`.
- Unattended runs (no user in the loop) may `add`, and `update` only an entry the extractor was shown
  (by index into the related list). The result is still a draft; deletes are never accepted.
- Only the user's own words are extraction sources (`select_sources`); assistant text is read-only
  context and runtime-appended messages are excluded (openspec 2026-11-06-memory-evolution stage 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

from . import text as memtext
from .service import CONFIDENCE_VALUES, CONTENT_LIMIT, KIND_VALUES, TITLE_LIMIT, parse_valid_until

#: Wait after a Run completes before its messages are read, so a conversation that is still going is not split.
CAPTURE_DELAY = timedelta(seconds=90)
#: Minimum time between two capture windows for the same session.
MIN_INTERVAL = timedelta(seconds=300)
#: Most messages read in one window; a longer backlog is handled by later windows.
MAX_MESSAGES_PER_WINDOW = 40
#: Messages more than this far apart start a new topic; a window never crosses a topic boundary.
TOPIC_GAP = timedelta(hours=1)
#: Model calls allowed per job. Attempts are capped at this number, so one job makes at most three calls.
MAX_ATTEMPTS = 3
#: Exponential backoff: `min(2 ** attempt * BACKOFF_BASE, BACKOFF_CAP)` seconds before the next attempt.
BACKOFF_BASE = timedelta(seconds=60)
BACKOFF_CAP = timedelta(hours=1)
#: Related published entries shown to the extractor, to keep it from proposing duplicates.
RELATED_LIMIT = 15
#: Most actions accepted from one extraction; the rest are dropped and counted as rejected.
MAX_ACTIONS = 10

#: Most valid actions kept from one extraction (WeKnora `extractMaxItemsPerRun`).
MAX_VALID_ACTIONS = 8
#: Evidence quotes per action, and the bounds of one quote (normalized minimum, raw maximum).
MAX_EVIDENCE = 3
QUOTE_MIN_CHARS = 4
QUOTE_MAX_CHARS = 200
TOPIC_LIMIT = TITLE_LIMIT
#: Most recent rejected topics shown to the extractor, and how far back they are read.
REJECTED_TOPIC_LIMIT = 20
REJECTED_TOPIC_WINDOW = timedelta(days=90)
#: Assistant context lines are cut to this many characters each.
CONTEXT_CHARS = 300
#: Origins of messages a person wrote: '' is the Run's initial message (stored without metadata),
#: `user_input` answers a question, `user_steer` is an instruction added while the Run was working.
USER_ORIGINS = ('', 'user_input', 'user_steer')
#: Kinds an extractor may add; `interest` comes only from topic counts (stage 6, D4).
EXTRACT_KINDS = ('memory', 'sop', 'profile')

OPS = ('add', 'update', 'delete', 'none')
UNATTENDED_OPS = ('add', 'update')


@dataclass(frozen=True)
class Message:
    """One conversation message eligible for capture."""
    sequence: int
    role: str
    content: str
    created_at: datetime
    id: str = ''
    #: `runtime_metadata.origin`; '' when the message has none (the Run's initial user message).
    origin: str = ''
    #: True for assistant messages that requested tools (their text is not conversation context).
    tool_calls: bool = False
    #: Reserved marker for system-generated messages (`runtime_metadata.synthetic`); never a source.
    synthetic: bool = False


@dataclass(frozen=True)
class Window:
    """Inclusive range of message sequences chosen for one capture job."""
    from_sequence: int
    through_sequence: int
    messages: tuple[Message, ...]


def aware(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC. SQLite returns naive datetimes; all stored values are UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def split_topics(messages: Sequence[Message]) -> list[list[Message]]:
    """Group messages (ordered by sequence) into topics, starting a new topic after a quiet gap."""
    topics: list[list[Message]] = []
    for message in sorted(messages, key=lambda m: m.sequence):
        if topics and aware(message.created_at) - aware(topics[-1][-1].created_at) < TOPIC_GAP:
            topics[-1].append(message)
        else:
            topics.append([message])
    return topics


def plan_window(messages: Sequence[Message], *, cursor: int, now: datetime,
                last_window_at: datetime | None) -> Window | None:
    """Choose the next window of unread messages, or None if capture should wait.

    Waits only when the minimum interval since the last window has not passed. The delay after a
    Run is applied by the caller as the job's `available_at` (`CAPTURE_DELAY`), so a window is
    planned when its Run completes. Takes the first topic that has unread messages, capped at
    `MAX_MESSAGES_PER_WINDOW`.
    """
    if last_window_at is not None and aware(now) - aware(last_window_at) < MIN_INTERVAL:
        return None
    unread = [m for m in messages if m.sequence > cursor]
    if not unread:
        return None
    topic = split_topics(unread)[0][:MAX_MESSAGES_PER_WINDOW]
    return Window(from_sequence=topic[0].sequence, through_sequence=topic[-1].sequence, messages=tuple(topic))


def backoff_seconds(attempt: int) -> int:
    """Seconds to wait after the `attempt`-th failure (1-based): `min(2 ** attempt * base, cap)`."""
    if attempt < 1:
        raise ValueError('attempt starts at 1')
    return int(min((2 ** attempt) * BACKOFF_BASE, BACKOFF_CAP).total_seconds())


@dataclass(frozen=True)
class ExtractorReply:
    """What a model-backed extractor may return instead of the bare parsed output: the output plus the
    token usage the provider reported (stage 5, D7). Bare outputs (scripted extractors) carry no usage."""
    actions: Any
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class Validation:
    """Accepted actions, the number of raw items that were rejected, and low-value items skipped.

    `low_value` items are well formed but below the value gate (importance <= 2 with low confidence);
    they are counted for the audit and never become drafts (openspec 2026-11-06-memory-evolution A5).
    """
    actions: list[dict[str, Any]] = field(default_factory=list)
    rejected: int = 0
    reasons: list[str] = field(default_factory=list)
    low_value: int = 0


def select_sources(messages: Sequence[Message]) -> tuple[list[Message], list[Message]]:
    """Split a window into extraction sources and read-only context (stage 1, A1/A9).

    Sources are user messages the person actually wrote: `role='user'` with an origin in
    `USER_ORIGINS` and not marked synthetic. Messages the runtime appends as `user` (continuation
    prompts, truncation notices, project context) carry `origin='runtime'` and are excluded, as are
    tool messages. Assistant text without tool calls is context only: it helps resolve references
    ("use the first one") but nothing may be recorded from it (WeKnora `collectSessionSegments`).
    """
    sources: list[Message] = []
    context: list[Message] = []
    for message in sorted(messages, key=lambda m: m.sequence):
        if not message.content.strip():
            continue
        if message.role == 'user' and message.origin in USER_ORIGINS and not message.synthetic:
            sources.append(message)
        elif message.role == 'assistant' and not message.tool_calls:
            context.append(message)
    return sources, context


def rank_related(sources: Sequence[Message], candidates: Sequence[dict[str, Any]], *,
                 limit: int = RELATED_LIMIT) -> list[dict[str, Any]]:
    """Pick the published entries the extractor should see for this window (stage 1, A2).

    `candidates` are dicts with `title`, `topic` and `content`, most recently updated first. Entries
    sharing more tokens with the user's words come first; when fewer than `limit` share any, the most
    recent remaining entries fill the list, so a short owner store is shown whole. The whole store is
    bounded by the character budget, so scoring in process is cheap (WeKnora `relevantExisting`).
    """
    window: set[str] = set()
    for message in sources:
        window |= memtext.token_set(message.content)
    scored = []
    for order, item in enumerate(candidates):
        tokens = memtext.token_set(' '.join(str(item.get(key, '')) for key in ('title', 'topic', 'content')))
        scored.append((len(window & tokens), order, item))
    relevant = sorted((row for row in scored if row[0] > 0), key=lambda row: (-row[0], row[1]))
    rest = [row for row in scored if row[0] == 0]
    return [item for _, _, item in (relevant + rest)[:limit]]


def validate_actions(raw: Any, *, unattended: bool, related: Sequence[dict[str, Any]] = (),
                     sources: Sequence[Message] | None = None, now: datetime | None = None) -> Validation:
    """Check extractor output against the action schema.

    Accepted item shapes (optional fields in brackets):
    - `{'op': 'add', 'kind': 'memory'|'sop', 'diff': str, [topic, importance, confidence, valid_until, evidence]}`
    - `{'op': 'update', 'target': int, 'diff': str, [...]}`: `target` indexes `related`; the action is
      resolved to that entry's id and current version. Unattended runs may update only this way.
    - `{'op': 'update', 'entry_id': uuid, 'base_version': int, 'diff': str}` (attended only)
    - `{'op': 'delete', ...}` is recognized but not stored
    - `{'op': 'none'}` is a no-op and is not counted as rejected

    When `sources` is given (automatic capture), every action needs `evidence`: one to three
    `{'seq', 'quote'}` items whose quote, normalized, occurs in that source message. Evidence is
    returned as `{'message_id', 'sequence', 'quote'}`. Optional fields that are malformed are dropped,
    not rejected; only the importance/confidence gate and the evidence check discard a whole item.
    Anything else is rejected. A non-list output rejects everything in it, as one reason. At most
    `MAX_VALID_ACTIONS` actions are kept from one output.
    """
    result = Validation()
    if not isinstance(raw, list):
        result.reasons.append('not_a_list')
        return result
    by_sequence = {message.sequence: message for message in sources} if sources is not None else None
    for item in raw[:MAX_ACTIONS]:
        verdict = _check_item(item, unattended=unattended, related=related, by_sequence=by_sequence, now=now)
        if verdict is None or verdict == 'none':
            continue
        if verdict == 'low_value':
            result.low_value += 1
            continue
        if isinstance(verdict, str):
            result.rejected += 1
            result.reasons.append(verdict)
            continue
        if len(result.actions) >= MAX_VALID_ACTIONS:
            result.rejected += 1
            result.reasons.append('too_many_actions')
            continue
        result.actions.append(verdict)
    result.rejected += max(0, len(raw) - MAX_ACTIONS)
    if len(raw) > MAX_ACTIONS:
        result.reasons.append('too_many_actions')
    return result


def _check_item(item: Any, *, unattended: bool, related: Sequence[dict[str, Any]],
                by_sequence: dict[int, Message] | None, now: datetime | None) -> dict[str, Any] | str | None:
    """Return a normalized action, `'none'` for a no-op, `'low_value'`, or a rejection reason string."""
    if not isinstance(item, dict):
        return 'not_an_object'
    op = item.get('op')
    if op not in OPS:
        return 'unknown_op'
    if op == 'none':
        return 'none'
    if unattended and op not in UNATTENDED_OPS:
        return 'unattended_op_not_allowed'
    if op == 'delete':
        return 'delete_not_supported'
    diff = item.get('diff')
    if not isinstance(diff, str) or not diff.strip():
        return 'missing_diff'
    if len(diff) > CONTENT_LIMIT:
        return 'diff_too_long'
    if op == 'add':
        kind = item.get('kind', 'memory')
        if kind not in EXTRACT_KINDS:
            return 'bad_kind'
        action: dict[str, Any] = {'op': 'add', 'kind': kind, 'diff': diff}
    elif 'target' in item:
        target = item.get('target')
        if isinstance(target, bool) or not isinstance(target, int) or not 0 <= target < len(related):
            return 'bad_target'
        entry = related[target]
        kind = item.get('kind', entry.get('kind'))
        if kind != entry.get('kind'):
            return 'kind_mismatch'
        action = {'op': 'update', 'kind': kind, 'entry_id': str(entry['id']),
                  'base_version': int(entry['version']), 'diff': diff}
    elif unattended:
        return 'bad_target'
    else:
        try:
            entry_id = UUID(str(item.get('entry_id')))
        except ValueError:
            return 'bad_entry_id'
        base_version = item.get('base_version')
        if not isinstance(base_version, int) or isinstance(base_version, bool) or base_version < 1:
            return 'bad_base_version'
        action = {'op': 'update', 'entry_id': entry_id, 'base_version': base_version, 'diff': diff}

    importance = item.get('importance')
    if isinstance(importance, int) and not isinstance(importance, bool) and 1 <= importance <= 5:
        action['importance'] = importance
    confidence = item.get('confidence')
    if confidence in CONFIDENCE_VALUES:
        action['confidence'] = confidence
    if action.get('importance', 3) <= 2 and action.get('confidence') == 'low':
        return 'low_value'
    topic = item.get('topic')
    if isinstance(topic, str) and topic.strip():
        action['topic'] = topic.strip()[:TOPIC_LIMIT]
    if 'valid_until' in item and now is not None:
        end = parse_valid_until(item.get('valid_until'), now)
        if end is not None:
            action['valid_until'] = end.isoformat()
    if by_sequence is not None:
        evidence = _check_evidence(item.get('evidence'), by_sequence)
        if isinstance(evidence, str):
            return evidence
        action['evidence'] = evidence
    return action


def _check_evidence(raw: Any, by_sequence: dict[int, Message]) -> list[dict[str, Any]] | str:
    """Validate quotes against the user's own messages (octop-memory `check_evidence`)."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_EVIDENCE:
        return 'bad_evidence'
    out = []
    for quote_item in raw:
        if not isinstance(quote_item, dict):
            return 'bad_evidence'
        sequence, quote = quote_item.get('seq'), quote_item.get('quote')
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence not in by_sequence:
            return 'bad_evidence'
        if not isinstance(quote, str) or len(quote) > QUOTE_MAX_CHARS:
            return 'bad_evidence'
        normalized = memtext.normalize_for_match(quote)
        message = by_sequence[sequence]
        if len(normalized) < QUOTE_MIN_CHARS or normalized not in memtext.normalize_for_match(message.content):
            return 'bad_evidence'
        out.append({'message_id': message.id, 'sequence': sequence, 'quote': quote.strip()})
    return out
