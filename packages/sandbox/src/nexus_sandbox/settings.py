"""``[sandbox]`` deployment settings: named profiles of type ``local``, ``docker`` or ``bwrap``.

(openspec 2026-11-07-skill-evolution, S2.) The operator defines profiles; an agent picks one by name and can never
create or change one. Each profile resolves to a :class:`SandboxSettings`, which is everything a backend, the manager
and the isolation acceptance need, so they work per profile without knowing about the others.

::

    [sandbox]
    enabled = false                  # the sandbox stays off until the operator turns it on
    default_profile = "local"        # used by agents that name no profile
    workspace_root = "data/sandbox"
    allow_local = false              # `local` profiles also need the development auth mode
    allow_local_scripts = false      # builtin skills declaring execution = "local" may run on a `local` profile

    [sandbox.profiles.docker]
    type = "docker"
    image = "python:3.12-slim"

Without ``profiles`` the older flat keys (``backend``, ``image``, ``cpus`` ...) describe a single profile named
``default``; with neither, the only profile is an implicit ``local`` one. Absent keys mean the defaults; invalid
values raise a safe error that names the key and never the value.

The ``local`` type is not an isolation boundary. Whether it may be used is decided where profiles are gated
(``sandbox_local_allowed``), not here: a configuration that names it is valid.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

from nexus_core.deployment import DeploymentConfigError, section

REMOTE_BACKENDS = ('ssh', 'managed')
BACKENDS = ('docker', 'bwrap', 'local', *REMOTE_BACKENDS)
NETWORKS = ('none', 'bridge')
PROFILE_NAME = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
PROFILE_POLICY_FIELDS = ('paused', 'exec_timeout_max_seconds', 'skill_timeout_seconds', 'skill_timeout_max_seconds')
_ENV_NAME = re.compile(r'^[A-Z_][A-Z0-9_]{0,63}$')
#: Host variables that must not be forwarded: anything that looks like a credential, and names the sandbox sets itself.
_SENSITIVE_ENV = re.compile(r'KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH|COOKIE', re.IGNORECASE)
_RESERVED_ENV = frozenset({'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'PYTHONPATH', 'NODE_PATH', 'USER', 'SHELL'})

#: Keys valid at the top of ``[sandbox]`` whatever the profile layout.
_TOP_KEYS = frozenset({'enabled', 'default_profile', 'workspace_root', 'allow_local', 'allow_local_scripts', 'profiles'})
#: Keys of the single flat profile of earlier configurations.
_LEGACY_KEYS = frozenset({'backend', 'image', 'cpus', 'memory_mb', 'pids', 'network', 'idle_seconds',
                          'workspace_quota_mb', 'exec_timeout_max_seconds'})
_COMMON_KEYS = frozenset({'type', 'display_name', 'description', 'workspace_quota_mb', 'exec_timeout_max_seconds', 'skill_timeout_seconds',
                          'skill_timeout_max_seconds', 'env_passthrough', 'build_timeout_seconds', 'env_max_mb',
                          'quota_mount', 'quota_project_start', 'quota_inodes'})
#: Keys each profile type accepts. A key that cannot take effect on a type is an error, not a silent no-op.
_TYPE_KEYS = {
    'docker': _COMMON_KEYS | {'image', 'cpus', 'memory_mb', 'pids', 'network', 'install_network', 'tmpfs_mb', 'idle_seconds'},
    'bwrap': _COMMON_KEYS | {'memory_mb', 'network', 'install_network', 'cgroup_root', 'cpus', 'pids'},
    'local': _COMMON_KEYS - {'quota_mount', 'quota_project_start', 'quota_inodes'},
    'ssh': (_COMMON_KEYS - {'env_passthrough', 'build_timeout_seconds', 'env_max_mb',
                            'quota_mount', 'quota_project_start', 'quota_inodes'})
    | {'ssh_host', 'ssh_user', 'ssh_port', 'ssh_identity_file', 'ssh_known_hosts', 'remote_profile', 'trusted_ssh'},
    'managed': (_COMMON_KEYS - {'env_passthrough', 'build_timeout_seconds', 'env_max_mb',
                                'quota_mount', 'quota_project_start', 'quota_inodes'})
    | {'endpoint', 'token_file', 'remote_profile', 'cpus', 'memory_mb', 'pids'},
}


@dataclass(frozen=True)
class SandboxSettings:
    """One profile, resolved. `backend` is the profile's type (``docker`` / ``bwrap`` / ``local``)."""
    display_name: str = ''
    description: str = ''
    configuration_id: str = ''
    enabled: bool = False
    backend: str = 'docker'
    image: str = 'python:3.12-slim'
    cpus: float = 1.0
    memory_mb: int = 512
    pids: int = 128
    network: str = 'none'
    #: Network of the temporary environment that builds a skill's dependencies; separate from the run-time network.
    install_network: str = 'bridge'
    tmpfs_mb: int = 64
    idle_seconds: int = 900
    workspace_quota_mb: int = 512
    exec_timeout_max_seconds: int = 120
    #: Timeouts of `exec_skill`: skill scripts are often slower than interactive commands.
    skill_timeout_seconds: int = 120
    skill_timeout_max_seconds: int = 600
    workspace_root: str = 'data/sandbox'
    #: Wall-clock limit and size limit of building one skill's dependency environment.
    build_timeout_seconds: int = 600
    env_max_mb: int = 512
    #: Host variable names forwarded into the sandbox. Empty by default; credential-like names are refused.
    env_passthrough: tuple[str, ...] = ()
    #: The local type is not an isolation boundary: development only, and additionally requires this.
    allow_local: bool = False
    allow_local_scripts: bool = False
    #: The profile's name; ``default`` for the flat legacy layout.
    profile: str = 'default'
    remote_profile: str = ''
    ssh_host: str = ''
    ssh_user: str = ''
    ssh_port: int = 22
    ssh_identity_file: str = ''
    ssh_known_hosts: str = ''
    trusted_ssh: bool = False
    endpoint: str = ''
    token_file: str = ''
    quota_mount: str = ''
    quota_project_start: int = 100000
    quota_inodes: int = 10000
    cgroup_root: str = ''
    paused: bool = False
    remote_policy_digest: str = ''
    remote_capabilities: dict = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return Path(self.workspace_root)

    @property
    def envs_root(self) -> Path:
        """Built dependency environments of this profile (one directory per skill version and environment)."""
        return self.root.resolve() / '_skill_envs' / self.profile

    @property
    def staging_root(self) -> Path:
        """Where an install works before anything is swapped in; emptied by the cleanup task."""
        return self.root.resolve() / '_staging'


@dataclass(frozen=True)
class SandboxConfig:
    """The whole ``[sandbox]`` section: top-level switches plus every profile."""
    enabled: bool = False
    default_profile: str = 'local'
    registry_revision: int = 0
    workspace_root: str = 'data/sandbox'
    allow_local: bool = False
    allow_local_scripts: bool = False
    profiles: dict[str, SandboxSettings] = field(default_factory=lambda: {'local': SandboxSettings(backend='local', profile='local')})

    def get(self, name: str | None = None) -> SandboxSettings | None:
        """The named profile, the default one for an empty name, or None when there is no such profile."""
        return self.profiles.get(name or self.default_profile)


def _invalid(where: str, key: str) -> DeploymentConfigError:
    return DeploymentConfigError(f'configs/nexus.toml [{where}].{key} is invalid')


def _pick(values: dict, where: str, key: str, kind: type, default, check=lambda v: True):
    value = values.get(key, default)
    number_ok = kind is not float or isinstance(value, (int, float))
    if isinstance(value, bool) != (kind is bool) or not (isinstance(value, kind) or (kind is float and number_ok)) or not check(value):
        raise _invalid(where, key)
    return float(value) if kind is float else value


def _env_names(values: dict, where: str) -> tuple[str, ...]:
    raw = values.get('env_passthrough', [])
    if not isinstance(raw, list) or len(raw) > 32:
        raise _invalid(where, 'env_passthrough')
    names: list[str] = []
    for item in raw:
        if (not isinstance(item, str) or not _ENV_NAME.match(item) or _SENSITIVE_ENV.search(item)
                or item in _RESERVED_ENV or item.startswith('NEXUS_') or item in names):
            raise _invalid(where, 'env_passthrough')
        names.append(item)
    return tuple(names)


def _profile(values: dict, where: str, name: str, top: dict, kind: str) -> SandboxSettings:
    """Build one profile from its table (or the legacy flat keys); `top` carries the section-wide switches."""
    defaults = SandboxSettings()
    timeout = _pick(values, where, 'skill_timeout_seconds', int, defaults.skill_timeout_seconds, lambda v: 1 <= v <= 3600)
    timeout_max = _pick(values, where, 'skill_timeout_max_seconds', int, defaults.skill_timeout_max_seconds, lambda v: 1 <= v <= 3600)
    if timeout > timeout_max:
        raise _invalid(where, 'skill_timeout_seconds')
    remote = {}
    if values.get('quota_mount') and 'quota_project_start' not in values:
        raise _invalid(where, 'quota_project_start')
    remote.update(
        quota_mount=_pick(values, where, 'quota_mount', str, '',
                          lambda v: v == '' or _absolute_path(v)),
        quota_project_start=_pick(values, where, 'quota_project_start', int, 100000,
                                  lambda v: 1 <= v <= 4000000000),
        quota_inodes=_pick(values, where, 'quota_inodes', int, 10000, lambda v: 100 <= v <= 1000000),
    )
    if kind == 'bwrap':
        group = _pick(values, where, 'cgroup_root', str, '', lambda v: v == '' or _absolute_path(v))
        if not group and ('cpus' in values or 'pids' in values):
            raise _invalid(where, 'cgroup_root')
        remote['cgroup_root'] = group
    if kind in REMOTE_BACKENDS:
        remote['remote_profile'] = _pick(values, where, 'remote_profile', str, '', PROFILE_NAME.fullmatch)
    if kind == 'ssh':
        remote.update(
            ssh_host=_pick(values, where, 'ssh_host', str, '', lambda v: re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', v)),
            ssh_user=_pick(values, where, 'ssh_user', str, '', lambda v: re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]{0,31}', v)),
            ssh_port=_pick(values, where, 'ssh_port', int, 22, lambda v: 1 <= v <= 65535),
            ssh_identity_file=_pick(values, where, 'ssh_identity_file', str, '', _absolute_path),
            ssh_known_hosts=_pick(values, where, 'ssh_known_hosts', str, '', _absolute_path),
            trusted_ssh=_pick(values, where, 'trusted_ssh', bool, False),
        )
    if kind == 'managed':
        remote.update(endpoint=_pick(values, where, 'endpoint', str, '', _https_endpoint).rstrip('/'),
                      token_file=_pick(values, where, 'token_file', str, '', _absolute_path))
    return SandboxSettings(
        enabled=top['enabled'], backend=kind,
        display_name=_pick(values, where, 'display_name', str, name, lambda v: 1 <= len(v.strip()) <= 160),
        description=_pick(values, where, 'description', str, '', lambda v: len(v) <= 1000),
        image=_pick(values, where, 'image', str, defaults.image, lambda v: bool(v.strip()) and ' ' not in v.strip()),
        cpus=_pick(values, where, 'cpus', float, defaults.cpus, lambda v: 0.1 <= v <= 16),
        memory_mb=_pick(values, where, 'memory_mb', int, defaults.memory_mb, lambda v: 64 <= v <= 16384),
        pids=_pick(values, where, 'pids', int, defaults.pids, lambda v: 16 <= v <= 4096),
        network=_pick(values, where, 'network', str, defaults.network, lambda v: v in NETWORKS),
        install_network=_pick(values, where, 'install_network', str, defaults.install_network, lambda v: v in NETWORKS),
        tmpfs_mb=_pick(values, where, 'tmpfs_mb', int, defaults.tmpfs_mb, lambda v: 1 <= v <= 4096),
        idle_seconds=_pick(values, where, 'idle_seconds', int, defaults.idle_seconds, lambda v: 30 <= v <= 86400),
        workspace_quota_mb=_pick(values, where, 'workspace_quota_mb', int, defaults.workspace_quota_mb, lambda v: 1 <= v <= 102400),
        exec_timeout_max_seconds=_pick(values, where, 'exec_timeout_max_seconds', int, defaults.exec_timeout_max_seconds,
                                       lambda v: 1 <= v <= 3600),
        skill_timeout_seconds=timeout, skill_timeout_max_seconds=timeout_max,
        build_timeout_seconds=_pick(values, where, 'build_timeout_seconds', int, defaults.build_timeout_seconds,
                                    lambda v: 10 <= v <= 7200),
        env_max_mb=_pick(values, where, 'env_max_mb', int, defaults.env_max_mb, lambda v: 16 <= v <= 20480),
        workspace_root=top['workspace_root'], env_passthrough=_env_names(values, where),
        allow_local=top['allow_local'], allow_local_scripts=top['allow_local_scripts'], profile=name, **remote)


def _absolute_path(value: str) -> bool:
    return bool(value) and not any(char.isspace() or char == '\x00' for char in value) and Path(value).is_absolute()


def _https_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (not any(char.isspace() or ord(char) < 32 for char in value) and '\\' not in value
                and parsed.scheme == 'https' and bool(parsed.hostname) and parsed.username is None
                and parsed.password is None and not parsed.query and not parsed.fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def _policy_path(settings: SandboxSettings) -> Path:
    return settings.root / '_profile_policies' / f'{settings.profile}.json'


def _policy_values(settings: SandboxSettings, values: dict) -> dict:
    where = f'sandbox.profiles.{settings.profile}'
    if values.keys() - set(PROFILE_POLICY_FIELDS) - {'remote_policy_digest', 'remote_capabilities'}:
        raise _invalid(where, 'policy')
    result = {key: _pick(values, where, key, int, getattr(settings, key), lambda v: 1 <= v <= 3600)
              for key in PROFILE_POLICY_FIELDS if key != 'paused'}
    result['paused'] = _pick(values, where, 'paused', bool, False)
    result['remote_policy_digest'] = _pick(
        values, where, 'remote_policy_digest', str, settings.remote_policy_digest,
        lambda value: value == '' or re.fullmatch(r'[a-f0-9]{64}', value),
    )
    capabilities = values.get('remote_capabilities', settings.remote_capabilities)
    if not isinstance(capabilities, dict) or len(json.dumps(capabilities)) > 4096:
        raise _invalid(where, 'remote_capabilities')
    result['remote_capabilities'] = capabilities
    if result['skill_timeout_seconds'] > result['skill_timeout_max_seconds']:
        raise _invalid(where, 'skill_timeout_seconds')
    return result


def save_profile_policy(settings: SandboxSettings, values: dict) -> dict:
    """Atomically persist non-credential policy fields on the shared workspace volume."""
    policy = _policy_values(settings, values)
    target = _policy_path(settings)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(policy | {'_configuration_id': settings.configuration_id}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o640)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return policy


def apply_profile_policy(settings: SandboxSettings) -> SandboxSettings:
    """Read the live policy for one operator-provisioned profile."""
    target = _policy_path(settings)
    try:
        with target.open(encoding='utf-8') as stream:
            values = json.loads(stream.read(8193))
    except FileNotFoundError:
        return settings
    except (OSError, ValueError):
        raise _invalid(f'sandbox.profiles.{settings.profile}', 'policy') from None
    if not isinstance(values, dict):
        raise _invalid(f'sandbox.profiles.{settings.profile}', 'policy')
    if values.pop('_configuration_id', '') != settings.configuration_id:
        paused = _pick(values, f'sandbox.profiles.{settings.profile}', 'paused', bool, False)
        return replace(settings, paused=paused)
    return replace(settings, **_policy_values(settings, values))


def load_config(path: Path | None = None, *, include_policies: bool = True) -> SandboxConfig:
    """Read ``[sandbox]`` into a :class:`SandboxConfig`. Raises DeploymentConfigError naming the key, never a value."""
    values = section('sandbox', path)
    top = {
        'enabled': _pick(values, 'sandbox', 'enabled', bool, False),
        'workspace_root': _pick(values, 'sandbox', 'workspace_root', str, 'data/sandbox', lambda v: bool(v.strip())),
        'allow_local': _pick(values, 'sandbox', 'allow_local', bool, False),
        'allow_local_scripts': _pick(values, 'sandbox', 'allow_local_scripts', bool, False),
    }
    raw_profiles = values.get('profiles')
    legacy = _LEGACY_KEYS & set(values)
    if raw_profiles is not None and legacy:
        raise _invalid('sandbox', sorted(legacy)[0])  # flat keys and profiles describe the same thing twice
    unknown = set(values) - _TOP_KEYS - _LEGACY_KEYS
    if unknown:
        raise DeploymentConfigError('configs/nexus.toml [sandbox] has an unknown key')

    profiles: dict[str, SandboxSettings] = {}
    if raw_profiles is not None:
        if not isinstance(raw_profiles, dict) or not raw_profiles:
            raise _invalid('sandbox', 'profiles')
        for name, table in raw_profiles.items():
            where = f'sandbox.profiles.{name}'
            if not isinstance(name, str) or not PROFILE_NAME.match(name) or not isinstance(table, dict):
                raise _invalid('sandbox', 'profiles')
            kind = table.get('type')
            if not isinstance(kind, str) or kind not in BACKENDS:
                raise _invalid(where, 'type')
            extra = set(table) - _TYPE_KEYS[kind]
            if extra:
                raise _invalid(where, sorted(extra)[0])
            profiles[name] = _profile(table, where, name, top, kind)
        default_profile = _pick(values, 'sandbox', 'default_profile', str, 'local' if 'local' in profiles else next(iter(profiles)))
    elif legacy:
        kind = _pick(values, 'sandbox', 'backend', str, 'docker', lambda v: v in ('docker', 'local', 'bwrap'))
        profiles['default'] = _profile(values, 'sandbox', 'default', top, kind)
        default_profile = _pick(values, 'sandbox', 'default_profile', str, 'default')
    else:
        profiles['local'] = _profile({}, 'sandbox', 'local', top, 'local')
        default_profile = _pick(values, 'sandbox', 'default_profile', str, 'local')
    config = SandboxConfig(enabled=top['enabled'], default_profile=default_profile, workspace_root=top['workspace_root'],
                           allow_local=top['allow_local'], allow_local_scripts=top['allow_local_scripts'], profiles=profiles)
    from .registry import merge
    config = merge(config)
    # The deployment default may reference a profile created through the console.
    # Validate against the merged catalog so that a typo cannot silently select local execution.
    if config.default_profile not in config.profiles:
        raise _invalid('sandbox', 'default_profile')
    if include_policies:
        config = replace(config, profiles={name: apply_profile_policy(settings) for name, settings in config.profiles.items()})
    return config


def configuration_revision() -> tuple:
    """A cheap cross-process cache key for deployment and console profile changes."""
    from nexus_core.deployment import config_path
    target = config_path()
    values = section('sandbox')
    root = _pick(values, 'sandbox', 'workspace_root', str, 'data/sandbox', lambda value: bool(value.strip()))
    registry = Path(root) / '_sandbox_profiles.json'
    def stamp(path):
        try:
            info = path.stat()
            return (info.st_mtime_ns, info.st_size, info.st_ino)
        except FileNotFoundError:
            return None
        except OSError:
            raise DeploymentConfigError('Sandbox configuration metadata is unavailable') from None
    return (str(target), stamp(target), str(registry.absolute()), stamp(registry))


def load_settings(path: Path | None = None, profile: str | None = None) -> SandboxSettings:
    """The settings of one profile (the default profile when `profile` is None). Raises when the profile is unknown."""
    selected = load_config(path).get(profile)
    if selected is None:
        raise DeploymentConfigError('configs/nexus.toml [sandbox] has no such profile')
    return selected


def sandbox_local_allowed(settings: SandboxSettings, *, development_mode: bool) -> bool:
    """Whether a `local` profile may be used: the operator allowed it and the platform runs in development auth mode."""
    return settings.allow_local and development_mode


def with_profile(settings: SandboxSettings, name: str) -> SandboxSettings:
    """A copy of `settings` under another profile name (tests and tools that build settings directly)."""
    return replace(settings, profile=name)
