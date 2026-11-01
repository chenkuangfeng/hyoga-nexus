"""Pure rules for automatic memory capture (openspec 2026-11-01-memory-optimization, stage 3).

Capture reads a finished conversation and proposes memory drafts. Everything here is deterministic
and free of I/O so the cadence, backoff and output validation can be tested without a database or model.

Contract notes:
- Extraction output is untrusted. `validate_actions` keeps only well-formed actions and counts the rest;
  nothing is stored from a rejected action.
- Capture never publishes. Valid actions become drafts through `service.propose` with `origin='capture'`.
- Unattended runs (no user in the loop) may only `add`. Edits and deletes need a person to review them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

from .service import CONTENT_LIMIT

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

OPS = ('add', 'update', 'delete', 'none')
UNATTENDED_OPS = ('add',)


@dataclass(frozen=True)
class Message:
    """One conversation message eligible for capture."""
    sequence: int
    role: str
    content: str
    created_at: datetime
    id: str = ''


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


@dataclass
class Validation:
    """Accepted actions and the number of raw items that were rejected."""
    actions: list[dict[str, Any]] = field(default_factory=list)
    rejected: int = 0
    reasons: list[str] = field(default_factory=list)


def validate_actions(raw: Any, *, unattended: bool) -> Validation:
    """Check extractor output against the action schema.

    Accepted item shapes:
    - `{'op': 'add', 'kind': 'memory'|'sop', 'diff': str}`
    - `{'op': 'update', 'entry_id': uuid, 'base_version': int, 'diff': str}` (attended only)
    - `{'op': 'delete', 'entry_id': uuid}` is recognized but not stored in this stage
    - `{'op': 'none'}` is a no-op and is not counted as rejected
    Anything else is rejected. A non-list output rejects everything in it, as one reason.
    """
    result = Validation()
    if not isinstance(raw, list):
        result.reasons.append('not_a_list')
        return result
    for item in raw[:MAX_ACTIONS]:
        verdict = _check_item(item, unattended=unattended)
        if verdict is None:
            continue
        if verdict == 'none':
            continue
        if isinstance(verdict, str):
            result.rejected += 1
            result.reasons.append(verdict)
            continue
        result.actions.append(verdict)
    result.rejected += max(0, len(raw) - MAX_ACTIONS)
    if len(raw) > MAX_ACTIONS:
        result.reasons.append('too_many_actions')
    return result


def _check_item(item: Any, *, unattended: bool) -> dict[str, Any] | str | None:
    """Return a normalized action, `'none'` for a no-op, or a rejection reason string."""
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
        if kind not in ('memory', 'sop'):
            return 'bad_kind'
        return {'op': 'add', 'kind': kind, 'diff': diff}
    # update
    try:
        entry_id = UUID(str(item.get('entry_id')))
    except ValueError:
        return 'bad_entry_id'
    base_version = item.get('base_version')
    if not isinstance(base_version, int) or isinstance(base_version, bool) or base_version < 1:
        return 'bad_base_version'
    return {'op': 'update', 'entry_id': entry_id, 'base_version': base_version, 'diff': diff}
