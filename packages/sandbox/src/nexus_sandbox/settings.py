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

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from nexus_core.deployment import DeploymentConfigError, section

BACKENDS = ('docker', 'bwrap', 'local')
NETWORKS = ('none', 'bridge')
PROFILE_NAME = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
_ENV_NAME = re.compile(r'^[A-Z_][A-Z0-9_]{0,63}$')
#: Host variables that must not be forwarded: anything that looks like a credential, and names the sandbox sets itself.
_SENSITIVE_ENV = re.compile(r'KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH|COOKIE', re.IGNORECASE)
_RESERVED_ENV = frozenset({'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'PYTHONPATH', 'NODE_PATH', 'USER', 'SHELL'})

#: Keys valid at the top of ``[sandbox]`` whatever the profile layout.
_TOP_KEYS = frozenset({'enabled', 'default_profile', 'workspace_root', 'allow_local', 'allow_local_scripts', 'profiles'})
#: Keys of the single flat profile of earlier configurations.
_LEGACY_KEYS = frozenset({'backend', 'image', 'cpus', 'memory_mb', 'pids', 'network', 'idle_seconds',
                          'workspace_quota_mb', 'exec_timeout_max_seconds'})
_COMMON_KEYS = frozenset({'type', 'workspace_quota_mb', 'exec_timeout_max_seconds', 'skill_timeout_seconds',
                          'skill_timeout_max_seconds', 'env_passthrough'})
#: Keys each profile type accepts. A key that cannot take effect on a type is an error, not a silent no-op.
_TYPE_KEYS = {
    'docker': _COMMON_KEYS | {'image', 'cpus', 'memory_mb', 'pids', 'network', 'install_network', 'tmpfs_mb', 'idle_seconds'},
    'bwrap': _COMMON_KEYS | {'memory_mb', 'network', 'install_network'},
    'local': _COMMON_KEYS,
}


@dataclass(frozen=True)
class SandboxSettings:
    """One profile, resolved. `backend` is the profile's type (``docker`` / ``bwrap`` / ``local``)."""
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
    #: Host variable names forwarded into the sandbox. Empty by default; credential-like names are refused.
    env_passthrough: tuple[str, ...] = ()
    #: The local type is not an isolation boundary: development only, and additionally requires this.
    allow_local: bool = False
    allow_local_scripts: bool = False
    #: The profile's name; ``default`` for the flat legacy layout.
    profile: str = 'default'

    @property
    def root(self) -> Path:
        return Path(self.workspace_root)


@dataclass(frozen=True)
class SandboxConfig:
    """The whole ``[sandbox]`` section: top-level switches plus every profile."""
    enabled: bool = False
    default_profile: str = 'local'
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
    return SandboxSettings(
        enabled=top['enabled'], backend=kind,
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
        workspace_root=top['workspace_root'], env_passthrough=_env_names(values, where),
        allow_local=top['allow_local'], allow_local_scripts=top['allow_local_scripts'], profile=name)


def load_config(path: Path | None = None) -> SandboxConfig:
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
            if kind not in BACKENDS:
                raise _invalid(where, 'type')
            extra = set(table) - _TYPE_KEYS[kind]
            if extra:
                raise _invalid(where, sorted(extra)[0])
            profiles[name] = _profile(table, where, name, top, kind)
        default_profile = _pick(values, 'sandbox', 'default_profile', str, 'local' if 'local' in profiles else next(iter(profiles)))
    elif legacy:
        kind = _pick(values, 'sandbox', 'backend', str, 'docker', lambda v: v in BACKENDS)
        profiles['default'] = _profile(values, 'sandbox', 'default', top, kind)
        default_profile = _pick(values, 'sandbox', 'default_profile', str, 'default')
    else:
        profiles['local'] = _profile({}, 'sandbox', 'local', top, 'local')
        default_profile = _pick(values, 'sandbox', 'default_profile', str, 'local')
    if default_profile not in profiles:
        raise _invalid('sandbox', 'default_profile')
    return SandboxConfig(enabled=top['enabled'], default_profile=default_profile, workspace_root=top['workspace_root'],
                         allow_local=top['allow_local'], allow_local_scripts=top['allow_local_scripts'], profiles=profiles)


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
