"""Configuration and gate rules for skill scripts (proposal 2026-11-04-skill-scripts, tasks 5.1–5.2)."""
import pytest

from nexus_platform.configuration import DatabaseConfigurationError, skill_scripts_allowed, skill_scripts_gate


def test_absent_skills_section_disables_scripts(tmp_path):
    path = tmp_path / 'nexus.toml'
    path.write_text('[auth]\nmode = "development"\n', encoding='utf-8')
    assert skill_scripts_allowed(path) is False


def test_allow_local_scripts_must_be_boolean(tmp_path):
    path = tmp_path / 'nexus.toml'
    path.write_text('[skills]\nallow_local_scripts = "yes"\n', encoding='utf-8')
    with pytest.raises(DatabaseConfigurationError, match='allow_local_scripts'):
        skill_scripts_allowed(path)


def test_explicit_true_is_read(tmp_path):
    path = tmp_path / 'nexus.toml'
    path.write_text('[skills]\nallow_local_scripts = true\n', encoding='utf-8')
    assert skill_scripts_allowed(path) is True


@pytest.mark.parametrize('auth_mode,backend,enabled,expected', [
    ('development', 'local', True, True),
    ('development', 'local', False, False),   # config flag missing
    ('production', 'local', True, False),     # not a development deployment
    (None, 'local', True, False),
    ('development', 'docker', True, False),   # no isolated backend passes acceptance yet
    ('development', None, True, False),
])
def test_all_three_conditions_are_required(auth_mode, backend, enabled, expected):
    assert skill_scripts_gate(auth_mode=auth_mode, backend=backend, config_enabled=enabled) is expected


def test_agent_skill_scripts_setting_defaults_on_and_must_be_boolean():
    from nexus_core.native import NativePolicy
    assert NativePolicy().skill_scripts is True
    with pytest.raises(ValueError):
        NativePolicy(skill_scripts='yes')
    assert NativePolicy(skill_scripts=False).skill_scripts is False
