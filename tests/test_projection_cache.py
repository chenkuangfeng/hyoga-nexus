"""Projection cache: immutable keys, LRU and idle eviction, size bound, no stored permissions."""
from uuid import uuid4

import pytest

from nexus_platform.sessions.projection_cache import ProjectionCache


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_same_key_is_built_once_and_then_served_from_cache():
    cache, session, calls = ProjectionCache(), uuid4(), []
    build = lambda: calls.append(1) or {'turns': 2}
    assert cache.get_or_build(session, 3, build) == {'turns': 2}
    assert cache.get_or_build(session, 3, build) == {'turns': 2}
    assert len(calls) == 1 and (cache.hits, cache.misses) == (1, 1)


def test_new_watermark_is_a_new_key_without_invalidation():
    cache, session = ProjectionCache(), uuid4()
    assert cache.get_or_build(session, 1, lambda: 'old') == 'old'
    assert cache.get_or_build(session, 2, lambda: 'new') == 'new'
    assert cache.get_or_build(session, 1, lambda: 'rebuilt') == 'old'  # old key still immutable


def test_least_recently_used_entry_is_evicted_first():
    cache, a, b, c = ProjectionCache(max_entries=2), uuid4(), uuid4(), uuid4()
    cache.get_or_build(a, 1, lambda: 'a'); cache.get_or_build(b, 1, lambda: 'b')
    cache.get_or_build(a, 1, lambda: 'x')  # touch a so b becomes least recent
    cache.get_or_build(c, 1, lambda: 'c')
    assert len(cache) == 2
    rebuilt = []
    assert cache.get_or_build(b, 1, lambda: rebuilt.append(1) or 'b2') == 'b2' and rebuilt == [1]


def test_idle_entries_expire_after_ttl():
    clock = Clock()
    cache, session = ProjectionCache(idle_ttl=10, clock=clock), uuid4()
    cache.get_or_build(session, 1, lambda: 'v')
    clock.now = 9
    assert cache.get_or_build(session, 1, lambda: 'other') == 'v'  # still fresh, read refreshes it
    clock.now = 25  # 16s since last read > ttl
    assert cache.get_or_build(session, 1, lambda: 'rebuilt') == 'rebuilt'


def test_oversized_projection_is_returned_but_not_stored():
    cache, session = ProjectionCache(max_entry_bytes=16), uuid4()
    big = {'text': 'x' * 100}
    assert cache.get_or_build(session, 1, lambda: big) == big
    assert len(cache) == 0


def test_non_json_projection_is_returned_but_not_stored():
    cache, session = ProjectionCache(), uuid4()
    marker = object()
    assert cache.get_or_build(session, 1, lambda: marker) is marker
    assert len(cache) == 0


@pytest.mark.parametrize('kwargs', [{'max_entries': 0}, {'idle_ttl': 0}, {'max_entry_bytes': 0}])
def test_invalid_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ProjectionCache(**kwargs)
