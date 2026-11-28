"""In-process projection cache keyed by immutable ``(session_id, watermark)``.

A session's projection (the view built from its snapshot and events) is a pure function of
that key. Events only append and the watermark only increases, so an entry for a given key
never goes stale and needs no invalidation. Capacity is bounded three ways:

- ``max_entries``: least-recently-used entries are evicted first;
- ``idle_ttl``: an entry not read for this many seconds is dropped on the next access;
- ``max_entry_bytes``: a projection whose JSON encoding exceeds this is returned but not stored.

Permissions are never cached here: callers must re-check them against the database on every
tool call or resource access, and must not feed authorization results into this cache.
The cache is process-local; a restart empties it, which is safe because keys are immutable.
"""
from __future__ import annotations

import json
from copy import deepcopy
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Hashable, TypeVar
from uuid import UUID

T = TypeVar("T")
Clock = Callable[[], float]


@dataclass
class _Entry:
    value: Any
    size: int
    last_used: float


class ProjectionCache:
    """Thread-safe LRU with idle expiry. ``get_or_build`` is the only read path."""

    def __init__(self, *, max_entries: int = 256, idle_ttl: float = 900.0,
                 max_entry_bytes: int = 256 * 1024, max_bytes: int = 16 * 1024 * 1024, clock: Clock | None = None) -> None:
        if max_entries < 1 or idle_ttl <= 0 or max_entry_bytes < 1 or max_bytes < 1:
            raise ValueError("cache limits must be positive")
        self.max_entries = max_entries
        self.idle_ttl = idle_ttl
        self.max_entry_bytes = max_entry_bytes
        self.max_bytes = max_bytes
        self._clock = clock or _monotonic
        self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_build(self, session_id: Hashable, watermark: int, build: Callable[[], T]) -> T:
        """Return the cached projection for ``(session_id, watermark)``, building it on a miss.

        ``build`` runs outside the lock, so two threads may build the same key concurrently;
        both results are equal by construction, and the first stored one is kept.
        """
        key = (session_id, watermark)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and now - entry.last_used <= self.idle_ttl:
                entry.last_used = now
                self._entries.move_to_end(key)
                self.hits += 1
                return deepcopy(entry.value)
            if entry is not None:
                del self._entries[key]
            self.misses += 1
        value = build()
        size = _encoded_size(value)
        if size is None or size > min(self.max_entry_bytes, self.max_bytes):
            return value
        with self._lock:
            if key not in self._entries:
                self._entries[key] = _Entry(value=deepcopy(value), size=size, last_used=self._clock())
            self._entries.move_to_end(key)
            self._expire_idle(self._clock())
            while len(self._entries) > self.max_entries or sum(e.size for e in self._entries.values()) > self.max_bytes:
                self._entries.popitem(last=False)
        return value

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _expire_idle(self, now: float) -> None:
        # Entries are ordered by use, so expired ones sit at the front.
        while self._entries:
            key, entry = next(iter(self._entries.items()))
            if now - entry.last_used <= self.idle_ttl:
                break
            del self._entries[key]


def _monotonic() -> float:
    import time
    return time.monotonic()


def _encoded_size(value: Any) -> int | None:
    """Byte length of the JSON encoding, or None if the value is not plain data (never cached)."""
    try:
        return len(json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return None
