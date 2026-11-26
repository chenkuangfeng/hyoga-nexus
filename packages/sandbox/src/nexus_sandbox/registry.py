"""Console-managed profile overrides on the API/worker shared control volume.

The registry keeps deployment-defined names compatible and uses a revision number to prevent stale
forms overwriting newer settings. Secrets remain deployment references or encrypted gateway settings.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from nexus_core.deployment import DeploymentConfigError
from .leases import mutation

if TYPE_CHECKING:
    from .settings import SandboxConfig, SandboxSettings

FILE = '_sandbox_profiles.json'


class RegistryConflict(Exception):
    """The submitted revision no longer matches the shared registry."""


def read(root: Path) -> dict:
    """Read a bounded registry, returning revision zero when absent and rejecting invalid storage."""
    try:
        with (root / FILE).open() as stream:
            raw = stream.read(262145)
        if len(raw) > 262144:
            raise ValueError
        data = json.loads(raw)
        if (not isinstance(data, dict) or type(data.get('revision')) is not int or data.get('revision', -1) < 0
                or not isinstance(data.get('profiles'), dict) or not isinstance(data.get('deleted'), list)
                or len(data['profiles']) > 100 or len(data['deleted']) > 1000):
            raise ValueError
        return data
    except FileNotFoundError:
        return {'revision': 0, 'profiles': {}, 'deleted': []}
    except (OSError, ValueError):
        raise DeploymentConfigError('Sandbox profile registry is invalid') from None


def merge(config: SandboxConfig) -> SandboxConfig:
    """Apply valid console overrides before per-profile runtime policy."""
    from .settings import BACKENDS, PROFILE_NAME, _TYPE_KEYS, _profile
    data = read(Path(config.workspace_root))
    profiles = dict(config.profiles)
    top = {'enabled': config.enabled, 'workspace_root': config.workspace_root,
           'allow_local': config.allow_local, 'allow_local_scripts': config.allow_local_scripts}
    for name, values in data['profiles'].items():
        if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name) or not isinstance(values, dict):
            raise DeploymentConfigError('Sandbox profile registry is invalid')
        kind = values.get('type')
        if not isinstance(kind, str) or kind not in BACKENDS or values.keys() - _TYPE_KEYS[kind]:
            raise DeploymentConfigError('Sandbox profile registry is invalid')
        settings = _profile(values, f'sandbox.profiles.{name}', name, top, kind)
        runtime = {key: value for key, value in values.items() if key not in ('display_name', 'description')}
        profiles[name] = replace(settings, configuration_id=hashlib.sha256(
            json.dumps(runtime, sort_keys=True).encode(),
        ).hexdigest()[:16])
    for name in data['deleted']:
        if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name):
            raise DeploymentConfigError('Sandbox profile registry is invalid')
        profiles.pop(name, None)
    return replace(config, profiles=profiles, registry_revision=data['revision'])


def configuration(settings: SandboxSettings) -> dict:
    """Return the type-specific deployment values, excluding runtime policy metadata."""
    from .settings import _TYPE_KEYS
    values = {key: getattr(settings, key) for key in _TYPE_KEYS[settings.backend] - {'type'}}
    if settings.backend == 'bwrap' and not settings.cgroup_root:
        values.pop('cpus', None)
        values.pop('pids', None)
    return {'type': settings.backend, **{key: list(value) if isinstance(value, tuple) else value
                                        for key, value in values.items()}}


def validate(config: SandboxConfig, name: str, values: dict) -> SandboxSettings:
    """Reuse deployment validation for console requests, including unsupported-key refusal."""
    from .settings import BACKENDS, PROFILE_NAME, _TYPE_KEYS, _profile
    kind = values.get('type')
    if (not PROFILE_NAME.fullmatch(name) or not isinstance(kind, str) or kind not in BACKENDS
            or values.keys() - _TYPE_KEYS[kind]):
        raise DeploymentConfigError('Sandbox profile parameters are invalid')
    top = {'enabled': config.enabled, 'workspace_root': config.workspace_root,
           'allow_local': config.allow_local, 'allow_local_scripts': config.allow_local_scripts}
    return _profile(values, f'sandbox.profiles.{name}', name, top, kind)


def write(config: SandboxConfig, name: str, values: dict | None, revision: int) -> None:
    """Atomically create/update an override or record a deletion, comparing the submitted revision."""
    root = Path(config.workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    with mutation(root, 'profile-registry'):
        data = read(root)
        if data['revision'] != revision:
            raise RegistryConflict
        if values is None:
            data['profiles'].pop(name, None)
            if name not in data['deleted']:
                data['deleted'].append(name)
        else:
            validate(config, name, values)
            if name in data['deleted']:
                raise RegistryConflict
            data['profiles'][name] = values
        data['revision'] += 1
        serialized = json.dumps(data, ensure_ascii=False)
        if len(serialized) > 262144 or len(data['profiles']) > 100 or len(data['deleted']) > 1000:
            raise DeploymentConfigError('Sandbox profile registry capacity exceeded')
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
                temporary.chmod(0o640)
                os.replace(temporary, root / FILE)
            finally:
                temporary.unlink(missing_ok=True)
