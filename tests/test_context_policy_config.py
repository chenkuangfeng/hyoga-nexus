"""Configuration contract for context and tool-output governance (openspec 2026-11-01-context-token-performance, design §14)."""
import pytest

from nexus_core.native import NativePolicy
from nexus_platform.runs import settings as native_settings


def test_defaults_match_the_specified_values():
    policy = NativePolicy()
    assert policy.tool_output_inline_limit == 2000
    assert policy.tool_preview_chars == 500
    assert policy.tool_output_page_chars == 4000
    assert policy.tool_result_window_rounds == 6
    assert policy.compact_high_ratio == 1.0
    assert policy.compact_low_ratio == 0.6
    assert policy.summary_max_chars == 8000
    assert policy.compaction_model_profile_version_id == ''
    assert policy.summarize_context is True
    assert policy.working_memory_tail is False


@pytest.mark.parametrize('override', [
    {'tool_output_inline_limit': 100},
    {'tool_output_inline_limit': True},
    {'tool_preview_chars': 3000},  # larger than the inline limit
    {'tool_output_page_chars': 100},
    {'tool_result_window_rounds': 0},
    {'summary_max_chars': 40000},
    {'compact_high_ratio': 0.2},
    {'compact_low_ratio': 1.0},  # not below the high ratio
    {'compaction_model_profile_version_id': 'not-a-uuid'},
    {'working_memory_tail': 1},
])
def test_invalid_values_are_rejected(override):
    with pytest.raises(ValueError):
        NativePolicy(**override)


def test_valid_compaction_model_identifier_is_accepted():
    identifier = '6f1c2a3e-1111-4222-8333-444455556666'
    assert NativePolicy(compaction_model_profile_version_id=identifier).compaction_model_profile_version_id == identifier


def test_validate_passes_new_keys_through_and_fills_missing_ones():
    result = native_settings.validate({
        'budgets': {},
        'behavior': {'tool_output_inline_limit': 3000, 'tool_preview_chars': 600},
    })
    assert result['behavior']['tool_output_inline_limit'] == 3000
    assert result['behavior']['tool_preview_chars'] == 600
    assert result['behavior']['summary_max_chars'] == 8000
    assert result['budgets']['max_tokens'] == 0


def test_run_cumulative_token_cap_accepts_unlimited_and_positive_values():
    unlimited = native_settings.validate({'budgets': {'max_tokens': 0}, 'behavior': {}})
    capped = native_settings.validate({'budgets': {'max_tokens': 32000}, 'behavior': {}})
    assert unlimited['budgets']['max_tokens'] == 0
    assert capped['budgets']['max_tokens'] == 32000


def test_validate_rejects_unknown_keys():
    with pytest.raises(ValueError):
        native_settings.validate({'budgets': {}, 'behavior': {'not_a_setting': 1}})


def test_stored_rows_without_new_keys_render_complete_defaults():
    stored = {'budgets': {'max_rounds': 50}, 'behavior': {'empty_retries': 1}}
    merged = native_settings._with_defaults(stored)
    assert merged['behavior']['empty_retries'] == 1
    assert merged['behavior']['tool_output_inline_limit'] == 2000
    assert merged['budgets']['max_rounds'] == 50
    assert set(merged['behavior']) == set(native_settings.defaults()['behavior'])
    # The stored record itself is not mutated.
    assert stored == {'budgets': {'max_rounds': 50}, 'behavior': {'empty_retries': 1}}


def test_every_setting_has_a_label():
    missing = set(native_settings.defaults()['behavior']) - set(native_settings.LABELS)
    assert not missing, missing
