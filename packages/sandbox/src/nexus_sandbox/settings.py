"""``[sandbox]`` deployment settings. Absent keys mean the defaults; invalid values raise a safe error."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nexus_core.deployment import DeploymentConfigError, section

BACKENDS = ('docker', 'bwrap', 'local')
NETWORKS = ('none', 'bridge')


@dataclass(frozen=True)
class SandboxSettings:
    """Deployment-side sandbox configuration. `enabled` defaults to false: the operator opts in."""
    enabled: bool = False
    backend: str = 'docker'
    image: str = 'python:3.12-slim'
    cpus: float = 1.0
    memory_mb: int = 512
    pids: int = 128
    network: str = 'none'
    idle_seconds: int = 900
    workspace_quota_mb: int = 512
    exec_timeout_max_seconds: int = 120
    workspace_root: str = 'data/sandbox'
    #: The local backend is not an isolation boundary: it is for development only and additionally requires this.
    allow_local: bool = False

    @property
    def root(self) -> Path:
        return Path(self.workspace_root)


def load_settings(path: Path | None = None) -> SandboxSettings:
    """Read ``[sandbox]``; raises DeploymentConfigError with the key name only (never a value)."""
    values = section('sandbox', path)
    defaults = SandboxSettings()

    def pick(key: str, kind: type, check=lambda v: True):
        value = values.get(key, getattr(defaults, key))
        number_ok = kind is not float or isinstance(value, (int, float))
        if isinstance(value, bool) != (kind is bool) or not (isinstance(value, kind) or (kind is float and number_ok)) or not check(value):
            raise DeploymentConfigError(f'configs/nexus.toml [sandbox].{key} is invalid')
        return float(value) if kind is float else value

    unknown = set(values) - set(SandboxSettings.__dataclass_fields__)
    if unknown:
        raise DeploymentConfigError('configs/nexus.toml [sandbox] has an unknown key')
    return SandboxSettings(
        enabled=pick('enabled', bool),
        backend=pick('backend', str, lambda v: v in BACKENDS),
        image=pick('image', str, lambda v: bool(v.strip()) and ' ' not in v.strip()),
        cpus=pick('cpus', float, lambda v: 0.1 <= v <= 16),
        memory_mb=pick('memory_mb', int, lambda v: 64 <= v <= 16384),
        pids=pick('pids', int, lambda v: 16 <= v <= 4096),
        network=pick('network', str, lambda v: v in NETWORKS),
        idle_seconds=pick('idle_seconds', int, lambda v: 30 <= v <= 86400),
        workspace_quota_mb=pick('workspace_quota_mb', int, lambda v: 1 <= v <= 102400),
        exec_timeout_max_seconds=pick('exec_timeout_max_seconds', int, lambda v: 1 <= v <= 3600),
        workspace_root=pick('workspace_root', str, lambda v: bool(v.strip())),
        allow_local=pick('allow_local', bool),
    )
