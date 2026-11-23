"""Encrypted provider provisioning for the standalone gateway's private state directory."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from nexus_platform.models.provider_settings import cipher
from nexus_sandbox.providers import provider_options
from nexus_core.sandbox import SandboxError


def load_providers(root: Path, profiles: dict, defaults: dict) -> dict:
    """Decrypt only records belonging to configured gateway profile names."""
    result = dict(defaults)
    for name in profiles:
        path = root / f'provider-{name}.encrypted'
        if not path.exists():
            continue
        record = json.loads(cipher().decrypt(path.read_bytes()))
        if record.pop('profile', None) != name:
            raise SandboxError('sandbox_provider_configuration_invalid')
        provider_options(record)
        result[name] = record
    return result


def save_provider(root: Path, name: str, values: dict, previous: dict | None) -> dict:
    """Validate and atomically replace a credential-bearing provider record, encrypted at rest."""
    if not isinstance(values, dict) or set(values) - {'type', 'template', 'domain', 'revision', 'api_key'}:
        raise SandboxError('sandbox_provider_configuration_invalid')
    if values.get('type') not in ('e2b', 'cubesandbox'):
        raise SandboxError('sandbox_provider_configuration_invalid')
    result = {key: values.get(key) for key in ('type', 'template', 'domain', 'revision')}
    if any(not isinstance(result[key], str) or not 1 <= len(result[key]) <= 256
           for key in ('template', 'domain', 'revision')):
        raise SandboxError('sandbox_provider_configuration_invalid')
    key = values.get('api_key')
    if key == '' or key is None:
        if previous is None:
            raise SandboxError('sandbox_provider_key_required')
        key = provider_options(previous)['api_key']
    if not isinstance(key, str) or not 1 <= len(key) <= 1024 or not all(33 <= ord(char) <= 126 for char in key):
        raise SandboxError('sandbox_provider_configuration_invalid')
    result['api_key'] = key
    provider_options(result)
    ciphertext = cipher().encrypt(json.dumps(result | {'profile': name}).encode())
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as stream:
        path = Path(stream.name)
        try:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(path, root / f'provider-{name}.encrypted')
        finally:
            path.unlink(missing_ok=True)
    return result


def public_provider(config: dict | None) -> dict:
    if config is None:
        return {'type': 'docker', 'template': '', 'domain': '', 'revision': '', 'has_api_key': False}
    return {key: config[key] for key in ('type', 'template', 'domain', 'revision')} | {'has_api_key': True}
