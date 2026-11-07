"""``[web]`` deployment settings. Absent keys mean the defaults; invalid values raise a safe error."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nexus_core.deployment import DeploymentConfigError, section

SEARCH_BACKENDS = ('', 'tavily', 'brave', 'searxng')


@dataclass(frozen=True)
class WebSettings:
    """Outbound web access. Off by default: the operator opts in, then each agent switches the group on."""
    enabled: bool = False
    #: One of SEARCH_BACKENDS; empty means web_search reports that no backend is configured.
    search_backend: str = ''
    search_api_key: str = ''
    #: Base URL of a SearXNG instance. The operator sets it, so it may be a private address.
    search_url: str = ''
    timeout_seconds: int = 15
    fetch_max_bytes: int = 2_000_000
    fetch_max_chars: int = 20_000


def load_settings(path: Path | None = None) -> WebSettings:
    """Read ``[web]``; raises DeploymentConfigError naming the key only, never a value."""
    values = section('web', path)
    defaults = WebSettings()
    unknown = set(values) - set(WebSettings.__dataclass_fields__)
    if unknown:
        raise DeploymentConfigError('configs/nexus.toml [web] has an unknown key')

    def pick(key: str, kind: type, check=lambda v: True):
        value = values.get(key, getattr(defaults, key))
        if isinstance(value, bool) != (kind is bool) or not isinstance(value, kind) or not check(value):
            raise DeploymentConfigError(f'configs/nexus.toml [web].{key} is invalid')
        return value

    settings = WebSettings(
        enabled=pick('enabled', bool),
        search_backend=pick('search_backend', str, lambda v: v in SEARCH_BACKENDS),
        search_api_key=pick('search_api_key', str),
        search_url=pick('search_url', str, lambda v: not v or v.startswith(('http://', 'https://'))),
        timeout_seconds=pick('timeout_seconds', int, lambda v: 1 <= v <= 120),
        fetch_max_bytes=pick('fetch_max_bytes', int, lambda v: 10_000 <= v <= 20_000_000),
        fetch_max_chars=pick('fetch_max_chars', int, lambda v: 1000 <= v <= 200_000),
    )
    if settings.search_backend in ('tavily', 'brave') and not settings.search_api_key:
        raise DeploymentConfigError('configs/nexus.toml [web].search_api_key is required for this backend')
    if settings.search_backend == 'searxng' and not settings.search_url:
        raise DeploymentConfigError('configs/nexus.toml [web].search_url is required for searxng')
    return settings
