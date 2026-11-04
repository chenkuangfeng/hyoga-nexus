"""Run watchdog: rule-based stall detection and derived attention state.

The watchdog observes a running Run from outside the execution loop and only *reports*: it appends
``run.watchdog_alert`` events and never cancels, retries or edits the Run. Detection is deterministic
(no model call) so its behaviour can be tested directly and cannot itself stall.

Rules implemented here (see openspec/changes/2026-11-04-run-watchdog):

* ``idle``: the Run is ``running`` and its newest event is older than ``idle_seconds``. Waiting for
  input or approval changes the Run status, so those waits are never reported as idle.
* ``repeat``: the newest ``repeat_threshold`` ``tool.started`` events carry the same tool name and
  arguments digest. Arguments are compared by digest, so the raw arguments are not copied into events.

The turn-count rule waits for the budget counters (roadmap 3.15) and is not implemented here.

Attention is derived from the event log instead of a stored column: a Run needs attention when its
newest alert is newer than every non-watchdog event and every acknowledgement. This keeps the
watchdog append-only and needs no migration.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

ALERT_EVENT = 'run.watchdog_alert'
ACK_EVENT = 'run.watchdog_ack'
TOOL_STARTED_EVENT = 'tool.started'
WATCHDOG_EVENTS = frozenset({ALERT_EVENT, ACK_EVENT})

RULE_IDLE = 'idle'
RULE_REPEAT = 'repeat'

#: Defaults from openspec/changes/2026-11-04-run-watchdog. They are estimates to be calibrated on real load.
DEFAULT_IDLE_SECONDS = 300
DEFAULT_REPEAT_THRESHOLD = 3
DEFAULT_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class WatchdogSettings:
    """Thresholds from ``[watchdog]``. Validation happens in the configuration reader, not here."""
    idle_seconds: int = DEFAULT_IDLE_SECONDS
    repeat_threshold: int = DEFAULT_REPEAT_THRESHOLD
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS


@dataclass(frozen=True)
class Alert:
    """One rule that is currently true. ``observed`` and ``threshold`` are written into the event payload."""
    rule: str
    observed: float | int
    threshold: float | int

    def payload(self) -> dict[str, object]:
        return {'rule': self.rule, 'observed': self.observed, 'threshold': self.threshold}


@dataclass(frozen=True)
class Observation:
    """A snapshot of one Run, read by the store inside the worker.

    ``tool_signatures`` lists the signatures of the most recent ``tool.started`` events, oldest first.
    ``last_event_at`` is None only when the Run has no events yet.
    """
    status: str
    now: datetime
    last_event_at: datetime | None
    tool_signatures: Sequence[str]


def tool_signature(name: str, arguments: str) -> str:
    """Stable identity of one tool call for repeat detection: the name plus a digest of its raw arguments.

    The digest is truncated to 16 hex characters. It is used only for equality within one Run, so
    collisions at that length are not a practical concern here.
    """
    digest = hashlib.sha256(arguments.encode('utf-8')).hexdigest()[:16]
    return f'{name}:{digest}'


def _aware(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; the platform stores UTC, so naive values are read as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def evaluate(observation: Observation, settings: WatchdogSettings) -> list[Alert]:
    """Return every rule that holds for this observation. Empty when the Run is not running or healthy.

    Only ``running`` Runs are checked: queued, waiting and terminal Runs are never reported.
    """
    if observation.status != 'running':
        return []
    alerts: list[Alert] = []
    if observation.last_event_at is not None:
        idle = (_aware(observation.now) - _aware(observation.last_event_at)).total_seconds()
        if idle > settings.idle_seconds:
            alerts.append(Alert(RULE_IDLE, int(idle), settings.idle_seconds))
    recent = list(observation.tool_signatures)[-settings.repeat_threshold:]
    if len(recent) >= settings.repeat_threshold and len(set(recent)) == 1:
        alerts.append(Alert(RULE_REPEAT, len(recent), settings.repeat_threshold))
    return alerts


def needs_attention(latest_alert: int, latest_clear: int) -> bool:
    """True when the newest alert sequence is newer than the newest clearing event sequence.

    Clearing events are every non-watchdog event and every ``run.watchdog_ack``; the caller computes
    both maxima in SQL. Zero means no such event exists.
    """
    return latest_alert > 0 and latest_alert > latest_clear
