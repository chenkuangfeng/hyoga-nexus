"""Smoke test for the fixed-session baseline harness (evals/context-performance).

Keeps the harness runnable and the fixed set complete. The numbers come from a scripted model, so
the test asserts structure and the direction of the spill effect, not absolute values.
"""
import importlib
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1] / 'evals' / 'context-performance'


def _harness():
    sys.path.insert(0, str(HARNESS_DIR))
    try:
        return importlib.import_module('harness'), importlib.import_module('cases')
    finally:
        sys.path.remove(str(HARNESS_DIR))


def test_fixed_set_has_twenty_sessions_and_all_complete():
    harness, cases = _harness()
    results = harness.run_all()
    assert len(results) == len(cases.CASES) == 20
    assert all(result['completed'] for result in results), [r['case'] for r in results if not r['completed']]
    for result in results:
        assert set(result['totals']) == {'requests', 'input_chars', 'transactions', 'events', 'wall_ms'}


def test_reader_keeps_the_model_input_small_for_long_outputs():
    harness, cases = _harness()
    by_name = {case.name: case for case in cases.CASES}
    with_reader = harness.run_case(by_name['followup-9000'])
    without_reader = harness.run_case(by_name['followup-no-reader-9000'])
    assert with_reader['totals']['input_chars'] < without_reader['totals']['input_chars']
