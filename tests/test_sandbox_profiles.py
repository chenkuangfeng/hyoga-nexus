"""Sandbox profiles: configuration, per-type parameters, forwarded variables and per-profile gating
(openspec 2026-11-07-skill-evolution, S2)."""
import asyncio
import os
import stat
import sys

import pytest

from nexus_core.deployment import DeploymentConfigError
from nexus_core.native import NativePolicy
from nexus_platform.runs import tool_gates
from nexus_platform.runs.tool_gates import GateFacts, hidden_groups, unavailable_groups
from nexus_sandbox import acceptance
from nexus_sandbox.backends.bwrap import BwrapBackend
from nexus_sandbox.backends.docker import DockerBackend, PROFILE_LABEL, container_name
from nexus_sandbox.backends.local import LocalExecutor
from nexus_sandbox.settings import SandboxSettings, load_config, load_settings, sandbox_local_allowed

@pytest.fixture
def db():
    """A session on an in-memory database holding the platform tables."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from nexus_platform.persistence.base import Base
    import nexus_platform.persistence.models  # noqa: F401  (registers the tables)
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        yield session
    engine.dispose()


FULL = '''
[sandbox]
enabled = true
default_profile = "docker"
workspace_root = "data/sbx"
allow_local = true
[sandbox.profiles.local]
type = "local"
[sandbox.profiles.docker]
type = "docker"
image = "img:1"
cpus = 2
memory_mb = 1024
pids = 64
network = "none"
install_network = "bridge"
tmpfs_mb = 32
env_passthrough = ["LANG_EXTRA", "PROXY_HOST"]
[sandbox.profiles.bwrap]
type = "bwrap"
network = "bridge"
memory_mb = 256
'''


def _config(tmp_path, body):
    path = tmp_path / 'nexus.toml'
    path.write_text(body, encoding='utf-8')
    return path


def test_profiles_are_resolved_with_their_own_parameters_and_the_shared_switches(tmp_path):
    config = load_config(_config(tmp_path, FULL))
    assert config.default_profile == 'docker' and set(config.profiles) == {'local', 'docker', 'bwrap'}
    docker = config.profiles['docker']
    assert (docker.backend, docker.image, docker.cpus, docker.memory_mb, docker.pids, docker.tmpfs_mb) == ('docker', 'img:1', 2.0, 1024, 64, 32)
    assert docker.env_passthrough == ('LANG_EXTRA', 'PROXY_HOST') and docker.install_network == 'bridge'
    assert (docker.enabled, docker.allow_local, docker.workspace_root, docker.profile) == (True, True, 'data/sbx', 'docker')
    assert config.profiles['bwrap'].network == 'bridge' and config.profiles['bwrap'].memory_mb == 256
    assert load_settings(_config(tmp_path, FULL)).profile == 'docker'  # the default profile
    assert load_settings(_config(tmp_path, FULL), 'bwrap').backend == 'bwrap'
    with pytest.raises(DeploymentConfigError):
        load_settings(_config(tmp_path, FULL), 'missing')


def test_the_older_flat_keys_describe_one_profile_named_default(tmp_path):
    config = load_config(_config(tmp_path, '[sandbox]\nenabled = true\nbackend = "bwrap"\nmemory_mb = 300\nnetwork = "bridge"'))
    assert config.default_profile == 'default' and list(config.profiles) == ['default']
    only = config.profiles['default']
    assert (only.backend, only.memory_mb, only.network, only.profile) == ('bwrap', 300, 'bridge', 'default')
    legacy_docker = load_config(_config(tmp_path, '[sandbox]\ncpus = 2'))  # no backend named: docker, as before
    assert legacy_docker.profiles['default'].backend == 'docker'


@pytest.mark.parametrize('body', [
    '[sandbox]\nbackend = "docker"\n[sandbox.profiles.a]\ntype = "local"',                       # flat keys and profiles together
    '[sandbox.profiles.a]\ntype = "vm"',                                                          # unknown type
    '[sandbox.profiles.a]\ntype = "bwrap"\npids = 10',                                          # key that cannot apply to the type
    '[sandbox.profiles.a]\ntype = "local"\nimage = "x"',
    '[sandbox.profiles.a]\ntype = "docker"\nextra_args = ["--privileged"]',                     # no verbatim docker arguments
    '[sandbox.profiles.A]\ntype = "local"',                                                       # bad profile name
    '[sandbox]\ndefault_profile = "ghost"\n[sandbox.profiles.a]\ntype = "local"',               # default must exist
    '[sandbox.profiles.a]\ntype = "docker"\nenv_passthrough = ["API_TOKEN"]',                   # credential-like name
    '[sandbox.profiles.a]\ntype = "docker"\nenv_passthrough = ["PATH"]',                        # a name the sandbox sets itself
    '[sandbox.profiles.a]\ntype = "docker"\nenv_passthrough = ["NEXUS_X"]',
    '[sandbox.profiles.a]\ntype = "docker"\nenv_passthrough = ["OK_NAME", "OK_NAME"]',
    '[sandbox.profiles.a]\ntype = "docker"\ninstall_network = "host"',
    '[sandbox.profiles.a]\ntype = "docker"\nskill_timeout_seconds = 900\nskill_timeout_max_seconds = 60',
    '[sandbox]\nprofiles = {}',
])
def test_invalid_profiles_are_rejected_without_echoing_values(tmp_path, body):
    with pytest.raises(DeploymentConfigError) as error:
        load_config(_config(tmp_path, body))
    for leaked in ('vm', 'host', 'API_TOKEN', '--privileged', 'ghost'):
        assert leaked not in str(error.value)


def test_a_local_profile_is_usable_only_in_development_mode_with_the_operator_switch():
    off, on = SandboxSettings(backend='local'), SandboxSettings(backend='local', allow_local=True)
    assert not sandbox_local_allowed(off, development_mode=True)
    assert not sandbox_local_allowed(on, development_mode=False)
    assert sandbox_local_allowed(on, development_mode=True)


# ------------------------------------------------------------------ parameters reach the backends

def test_docker_arguments_follow_the_profile(tmp_path):
    settings = SandboxSettings(enabled=True, backend='docker', profile='strict', tmpfs_mb=32, env_passthrough=('PROXY_HOST',))
    os.environ['PROXY_HOST'] = 'proxy.internal'
    try:
        args = DockerBackend(settings).run_arguments('n', tmp_path / 'w', tmp_path / 'o')
    finally:
        del os.environ['PROXY_HOST']
    joined = ' '.join(args)
    assert '--tmpfs /tmp:rw,size=32m' in joined and f'--label {PROFILE_LABEL}=strict' in joined
    assert '-e PROXY_HOST=proxy.internal' in joined
    assert '--cap-drop ALL' in joined and '--read-only' in joined  # the hardening is not part of the profile


def test_a_variable_that_is_not_set_is_not_forwarded(tmp_path):
    settings = SandboxSettings(enabled=True, backend='docker', env_passthrough=('NEXUS_TEST_UNSET_VARIABLE',))
    assert 'NEXUS_TEST_UNSET_VARIABLE' not in ' '.join(DockerBackend(settings).run_arguments('n', tmp_path, tmp_path))


def test_container_names_keep_the_default_and_separate_the_other_profiles():
    assert container_name('t', 's') == container_name('t', 's', 'default')
    assert container_name('t', 's', 'strict') != container_name('t', 's')
    assert container_name('t', 's', 'strict') != container_name('t', 's', 'other')


def test_bwrap_forwards_only_the_listed_variables(tmp_path):
    os.environ['NEXUS_FWD_A'], os.environ['NEXUS_FWD_B'] = 'a', 'b'
    try:
        settings = SandboxSettings(enabled=True, backend='bwrap', profile='b', env_passthrough=('NEXUS_FWD_A',))
        args = BwrapBackend(settings).jail_arguments(tmp_path / 'w', tmp_path / 'o', '/workspace', 'true')
    finally:
        del os.environ['NEXUS_FWD_A'], os.environ['NEXUS_FWD_B']
    assert args[args.index('NEXUS_FWD_A') - 1] == '--setenv' and 'NEXUS_FWD_B' not in args


def test_local_executor_forwards_only_the_listed_variables(tmp_path):
    (tmp_path / 'w').mkdir()
    os.environ['FWD_LISTED'], os.environ['FWD_OTHER'] = 'yes', 'no'
    try:
        executor = LocalExecutor({'/workspace': tmp_path / 'w', '/outputs': tmp_path / 'w'}, ('FWD_LISTED',))
        result = asyncio.run(executor.run('echo "${FWD_LISTED:-}|${FWD_OTHER:-}"', cwd='/workspace', timeout_seconds=5, output_limit=200))
    finally:
        del os.environ['FWD_LISTED'], os.environ['FWD_OTHER']
    assert result.stdout.strip() == 'yes|'


# ------------------------------------------------------------------ reports and gating per profile

def test_each_profile_keeps_its_own_acceptance_report(tmp_path):
    root = str(tmp_path / 'sbx')
    legacy = SandboxSettings(enabled=True, backend='docker', workspace_root=root)
    named = SandboxSettings(enabled=True, backend='docker', workspace_root=root, profile='strict')
    assert acceptance.report_path(legacy).name == 'acceptance.json'
    assert acceptance.report_path(named).name == 'acceptance-strict.json'
    assert acceptance.fingerprint(named) != acceptance.fingerprint(SandboxSettings(backend='docker', tmpfs_mb=8))


def _facts(monkeypatch, tmp_path, body, mode='development'):
    path = _config(tmp_path, body)
    monkeypatch.setattr('nexus_core.deployment.config_path', lambda: path)
    monkeypatch.setattr('nexus_platform.configuration.auth_settings', lambda: type('A', (), {'mode': mode})())
    monkeypatch.setattr(tool_gates, '_web_enabled', lambda: False)


def test_gating_follows_the_agents_profile(db, monkeypatch, tmp_path):
    _facts(monkeypatch, tmp_path, FULL)
    assert tool_gates.deployment_gate_facts(db, 'local').sandbox_accepted is True            # allow_local and development mode
    assert unavailable_groups(tool_gates.deployment_gate_facts(db, 'docker'))['sandbox'] == 'sandbox_not_accepted'
    assert unavailable_groups(tool_gates.deployment_gate_facts(db, 'ghost'))['sandbox'] == 'sandbox_profile_unknown'
    assert tool_gates.deployment_gate_facts(db, '').sandbox_accepted is False                # the empty name is the default: docker


def test_a_local_profile_is_unavailable_outside_development_mode(db, monkeypatch, tmp_path):
    _facts(monkeypatch, tmp_path, FULL, mode='production')
    facts = tool_gates.deployment_gate_facts(db, 'local')
    assert unavailable_groups(facts)['sandbox'] == 'sandbox_local_not_allowed'
    assert 'sandbox' in hidden_groups(facts, {'sandbox': True})


def test_local_profile_is_unavailable_in_production_without_failing(db, monkeypatch, tmp_path):
    _facts(monkeypatch, tmp_path, '[sandbox]\nenabled = true', mode='production')
    assert unavailable_groups(tool_gates.deployment_gate_facts(db, 'local'))['sandbox'] == 'sandbox_local_not_allowed'


def test_a_disabled_or_broken_section_leaves_the_sandbox_off(db, monkeypatch, tmp_path):
    _facts(monkeypatch, tmp_path, '[sandbox]\nenabled = false')
    assert unavailable_groups(tool_gates.deployment_gate_facts(db))['sandbox'] == 'sandbox_disabled'
    _facts(monkeypatch, tmp_path, '[sandbox]\nsurprise = 1')
    assert unavailable_groups(tool_gates.deployment_gate_facts(db))['sandbox'] == 'sandbox_disabled'


def test_the_editor_lists_the_profiles_with_their_availability(db, monkeypatch, tmp_path):
    _facts(monkeypatch, tmp_path, FULL)
    listed = {p['name']: p for p in tool_gates.sandbox_profiles(db)}
    assert listed['docker']['default'] and not listed['docker']['available'] and listed['docker']['reason'] == 'sandbox_not_accepted'
    assert listed['local']['available'] and listed['local']['type'] == 'local'
    _facts(monkeypatch, tmp_path, '[sandbox]\nenabled = false')
    assert tool_gates.sandbox_profiles(db) == []


def test_the_agent_policy_accepts_only_profile_names():
    assert NativePolicy().sandbox_profile == '' and NativePolicy(sandbox_profile='strict-2').sandbox_profile == 'strict-2'
    for bad in ('Strict', 'has space', '../x', 'x' * 40):
        with pytest.raises(ValueError):
            NativePolicy(sandbox_profile=bad)


# ------------------------------------------------------------------ the tool definitions follow the profiles

def _exec_tool(monkeypatch, tmp_path, body):
    from nexus_tools.builtins.sandbox import sandbox_tools
    path = _config(tmp_path, body)
    monkeypatch.setattr('nexus_core.deployment.config_path', lambda: path)
    return next(tool.definition for tool in sandbox_tools() if tool.definition.name == 'sandbox_exec')


@pytest.mark.parametrize('body, risk, timeout', [
    ('', 'write', 135),
    ('[sandbox.profiles.d]\ntype = "docker"\n[sandbox.profiles.b]\ntype = "bwrap"', 'write', 135),
    ('[sandbox.profiles.d]\ntype = "docker"\n[sandbox.profiles.b]\ntype = "bwrap"\nnetwork = "bridge"', 'destructive', 135),
    ('[sandbox.profiles.d]\ntype = "docker"\nnetwork = "bridge"\nexec_timeout_max_seconds = 300', 'destructive', 315),
    ('[sandbox.profiles.l]\ntype = "local"\nexec_timeout_max_seconds = 30', 'write', 45),   # local is not counted as a network
    ('[sandbox]\nnetwork = "bridge"', 'destructive', 135),                                 # the older flat layout
    ('[sandbox]\nexec_timeout_max_seconds = 60', 'write', 75),
    ('[sandbox\nbroken', 'destructive', 135),                                              # unreadable: the cautious answer
])
def test_sandbox_exec_risk_and_timeout_follow_the_profiles(monkeypatch, tmp_path, body, risk, timeout):
    definition = _exec_tool(monkeypatch, tmp_path, body)
    assert definition.risk == risk and definition.timeout_seconds == timeout


# ------------------------------------------------------------------ reports in the database (design 2.3.1)

def _report(settings, *, passed=True, fingerprint=None):
    return {'passed': passed, 'fingerprint': fingerprint or acceptance.fingerprint(settings), 'backend': settings.backend,
            'checked_at': '2026-11-11T08:00:00Z', 'items': [{'name': 'network', 'ok': passed, 'detail': ''}]}


def test_the_database_store_round_trips_and_replaces_one_row_per_profile(db, tmp_path):
    from nexus_platform.runs.sandbox_acceptance import DbReportStore
    settings = SandboxSettings(enabled=True, backend='docker', workspace_root=str(tmp_path), profile='strict')
    store = DbReportStore(db)
    assert store.load(settings) is None
    store.save(settings, _report(settings, passed=False))
    store.save(settings, _report(settings))
    loaded = store.load(settings)
    assert loaded['passed'] is True and loaded['items'][0]['name'] == 'network' and loaded['checked_at'] == '2026-11-11T08:00:00Z'
    other = SandboxSettings(enabled=True, backend='docker', workspace_root=str(tmp_path), profile='other')
    assert store.load(other) is None


def test_a_database_report_decides_and_a_changed_fingerprint_invalidates_it(db, tmp_path):
    from nexus_platform.runs.sandbox_acceptance import DbReportStore
    settings = SandboxSettings(enabled=True, backend='docker', workspace_root=str(tmp_path))
    store = DbReportStore(db)
    assert acceptance.passed(settings, store) is False
    store.save(settings, _report(settings))
    assert acceptance.passed(settings, store) is True
    changed = SandboxSettings(enabled=True, backend='docker', workspace_root=str(tmp_path), tmpfs_mb=8)
    assert acceptance.passed(changed, store) is False  # the same profile, different limits


def test_the_row_wins_over_an_older_file_and_a_file_is_used_only_without_a_row(db, tmp_path):
    from nexus_platform.runs.sandbox_acceptance import DbReportStore
    settings = SandboxSettings(enabled=True, backend='docker', workspace_root=str(tmp_path))
    store = DbReportStore(db)
    acceptance.FileReportStore().save(settings, _report(settings))
    assert acceptance.passed(settings, store) is True            # no row: the report made before the table counts
    store.save(settings, _report(settings, passed=False))
    assert acceptance.passed(settings, store) is False           # the row says failed; the old file no longer counts


def test_an_unreadable_store_means_not_accepted_even_with_a_valid_file(tmp_path):
    settings = SandboxSettings(enabled=True, backend='docker', workspace_root=str(tmp_path))
    acceptance.FileReportStore().save(settings, _report(settings))

    class Broken:
        def load(self, _settings):
            raise RuntimeError('database down')
    assert acceptance.passed(settings, Broken()) is False
    assert acceptance.passed(settings) is True                    # without a store the file still counts


def test_gating_reads_the_database_report(db, monkeypatch, tmp_path):
    from nexus_platform.runs.sandbox_acceptance import DbReportStore
    _facts(monkeypatch, tmp_path, FULL)
    assert unavailable_groups(tool_gates.deployment_gate_facts(db, 'docker'))['sandbox'] == 'sandbox_not_accepted'
    settings = load_config().get('docker')
    DbReportStore(db).save(settings, _report(settings))
    assert 'sandbox' not in unavailable_groups(tool_gates.deployment_gate_facts(db, 'docker'))
    assert {p['name']: p['available'] for p in tool_gates.sandbox_profiles(db)}['docker'] is True


def test_the_sandbox_package_does_not_import_the_platform():
    import subprocess
    code = "import sys, nexus_sandbox.acceptance; assert not any(m.startswith('nexus_platform') for m in sys.modules)"
    assert subprocess.run([sys.executable, '-c', code]).returncode == 0


def test_the_worker_startup_check_reports_unaccepted_profiles_without_running_probes(db, monkeypatch, tmp_path, caplog):
    from nexus_platform.runs.sandbox_acceptance import DbReportStore
    from nexus_worker.__main__ import sandbox_startup_check
    _facts(monkeypatch, tmp_path, FULL)

    class Factory:
        def __call__(self):
            return self
        def __enter__(self):
            return db
        def __exit__(self, *_):
            return False
    with caplog.at_level('WARNING', logger='nexus_worker'):
        assert sorted(sandbox_startup_check(Factory())) == ['bwrap', 'docker']   # `local` is never accepted, so never listed
    assert 'sandbox-check' in caplog.text
    for name in ('docker', 'bwrap'):
        settings = load_config().get(name)
        DbReportStore(db).save(settings, _report(settings))
    assert sandbox_startup_check(Factory()) == []
    _facts(monkeypatch, tmp_path, '[sandbox]\nenabled = false')
    assert sandbox_startup_check(Factory()) == []


def test_console_profiles_reload_worker_and_keep_runtime_identity(tmp_path, monkeypatch):
    from nexus_sandbox.registry import configuration, validate, write
    from nexus_sandbox.settings import load_config
    from nexus_worker import sandbox_runtime

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs' / 'nexus.toml').write_text(f'''
[sandbox]
enabled = true
workspace_root = "{tmp_path / 'shared'}"
''')
    sandbox_runtime._config.cache_clear()
    sandbox_runtime._managers.clear()
    try:
        config = load_config()
        settings = validate(config, 'new_docker', {'type': 'docker', 'display_name': 'Docker'})
        write(config, 'new_docker', configuration(settings), 0)
        first = sandbox_runtime.manager('new_docker')
        assert first is not None
        first_id = first.settings.configuration_id
        changed = configuration(first.settings) | {'memory_mb': 1024}
        write(load_config(), 'new_docker', changed, 1)
        second = sandbox_runtime.manager('new_docker')
        assert second.settings.memory_mb == 1024 and second.settings.configuration_id != first_id
        metadata = configuration(second.settings) | {'display_name': 'Renamed'}
        write(load_config(), 'new_docker', metadata, 2)
        assert sandbox_runtime.manager('new_docker').settings.configuration_id == second.settings.configuration_id
    finally:
        sandbox_runtime._config.cache_clear()
        sandbox_runtime._managers.clear()


def test_worker_invalid_console_registry_root_stays_unavailable(tmp_path, monkeypatch):
    """The revision probe must fail closed on malformed deployment settings."""
    from nexus_worker import sandbox_runtime
    path = tmp_path / 'nexus.toml'
    path.write_text('[sandbox]\nenabled = true\nworkspace_root = 42\n')
    monkeypatch.setattr('nexus_core.deployment.config_path', lambda: path)
    assert sandbox_runtime.manager() is None


def test_deployment_default_can_select_console_profile(tmp_path):
    """Resolve defaults after console overrides, while rejecting missing/deleted defaults."""
    from nexus_sandbox.registry import write

    path = tmp_path / 'nexus.toml'
    body = f'[sandbox]\nworkspace_root = "{tmp_path / "shared"}"\n'
    path.write_text(body)
    write(load_config(path), 'production', {'type': 'docker'}, 0)
    path.write_text(body + 'default_profile = "production"\n')
    assert load_config(path).get().backend == 'docker'
    write(load_config(path), 'production', None, 1)
    with pytest.raises(DeploymentConfigError):
        load_config(path)


def test_missing_configuration_enables_docker_and_local_but_preserves_explicit_choices(tmp_path):
    """Defaults create no containers and never overwrite operator choices or tombstones."""
    from nexus_sandbox.registry import write
    from nexus_sandbox.settings import SandboxConfig
    path = tmp_path / 'nexus.toml'
    root = tmp_path / 'shared'
    path.write_text(f'[sandbox]\nworkspace_root = "{root}"\n')
    config = load_config(path)
    assert config.enabled and config.allow_local
    assert config.default_profile == 'docker' and set(config.profiles) == {'docker', 'local'}
    assert all(settings.enabled and settings.allow_local for settings in config.profiles.values())
    assert SandboxConfig().default_profile == config.default_profile
    assert set(SandboxConfig().profiles) == set(config.profiles)
    write(config, 'local', None, 0)
    assert set(load_config(path).profiles) == {'docker'}
    path.write_text(f'[sandbox]\nenabled = false\nallow_local = false\nworkspace_root = "{root}"\n')
    disabled = load_config(path)
    assert not disabled.enabled and not disabled.allow_local
    path.write_text(f'[sandbox]\nworkspace_root = "{root}"\n[sandbox.profiles.custom]\ntype = "docker"\n')
    custom = load_config(path)
    assert set(custom.profiles) == {'custom'} and custom.default_profile == 'custom'
