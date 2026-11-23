"""Gateway ownership, policy identity and persistent recovery of isolated executions."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from uuid import uuid4

from nexus_core.sandbox import SandboxError
from . import acceptance
from .backends.docker import DockerBackend, container_name, run_cli
from .lifecycle import Journal
from .providers import provider_identity, recover_provider
from .settings import SandboxSettings

logger = logging.getLogger(__name__)


class GatewayState:
    """Own one durable node journal. A policy digest covers its node and execution environment."""

    def __init__(self, root: Path, profiles: dict, providers: dict):
        self.journal = Journal(root)
        self.profiles, self.providers = profiles, providers
        node = root / 'node-id'
        if not node.exists():
            node.write_text(uuid4().hex)
        self.node_id = node.read_text().strip()

    async def capabilities(self, name: str, settings: SandboxSettings) -> dict:
        provider = self.providers.get(name)
        if provider:
            image = provider_identity(provider)
        else:
            code, value, _ = await run_cli('docker', 'image', 'inspect', '--format', '{{.Id}}', settings.image)
            if code or not value.strip().startswith('sha256:'):
                raise SandboxError('sandbox_image_unavailable')
            image = value.strip()
        digest = hashlib.sha256(json.dumps({
            'node': self.node_id, 'runtime': 'nexus-gateway-v2', 'image': image,
            'settings': acceptance.fingerprint(settings),
            'adapter': hashlib.sha256(b''.join(
                (Path(__file__).parent / filename).read_bytes()
                for filename in ('providers.py', 'provider_runner.py', 'transfer.py', 'remote_runner.py',
                                 'backends/output.py', 'backends/docker/__init__.py')
            )).hexdigest(),
        }, sort_keys=True).encode()).hexdigest()
        return {'policy_digest': digest, 'provider': provider['type'] if provider else 'docker',
                'file_transfer': 'snapshot' if provider else 'shared_volume',
                'background': False, 'build': False, 'network': 'none',
                'output_capture': 'bounded', 'cleanup': 'persistent',
                'template_revision': provider.get('revision') if provider else image}

    async def recover(self, active: set[str]) -> None:
        """Retry cleanup only, keeping uncertain creates pending through their hard VM lifetime."""
        for record in self.journal.pending():
            if record['id'] in active:
                continue
            try:
                self.journal.write(record['id'], state='cleanup_pending')
                if not record.get('expires_at') and not record.get('container_name'):
                    self.journal.write(record['id'], state='finished')
                    continue
                settings = self.profiles.get(record['profile'])
                if settings is None:
                    continue
                if record.get('tenant_id') and record.get('session_id'):
                    from .leases import hold, session_name
                    from .transfer import recover_publication
                    base = settings.root / record['tenant_id'] / record['session_id']
                    async with hold(settings.root, session_name(record['tenant_id'], record['session_id'])):
                        await asyncio.to_thread(recover_publication, base)
                provider = self.providers.get(record['profile'])
                if provider:
                    await recover_provider(record, provider, self.journal)
                else:
                    name = record.get('container_name')
                    if name:
                        await DockerBackend(settings, lifetime=1).remove(name)
                    if record.get('expires_at', 0) < time.time():
                        self.journal.write(record['id'], state='finished')
            except Exception:
                logger.warning('Sandbox cleanup remains pending for request %s', record['id'])

    def reserve(self, execution) -> None:
        self.journal.reserve(execution.id, execution.profile)
        self.journal.write(execution.id, tenant_id=execution.tenant_id, session_id=execution.session_id)
        if execution.profile not in self.providers:
            self.journal.write(execution.id, container_name=container_name(
                execution.tenant_id, f'{execution.session_id}-{execution.id}', execution.profile,
            ), expires_at=time.time() + execution.timeout_seconds + 120)

    async def execute_docker(self, execution, settings, run):
        self.journal.write(execution.id, state='running')
        completed = False
        try:
            result = await run(execution, settings, backend='docker')
            completed = True
            return result
        finally:
            # A crash during create/exec leaves this record pending for startup recovery.
            self.journal.write(execution.id, state='cleanup_pending')
            name = self.journal.get(execution.id)['container_name']
            from .lifecycle import drain
            await drain(DockerBackend(settings, lifetime=1).remove(name))
            if completed:
                self.journal.write(execution.id, state='finished')

    async def execute_provider(self, execution, settings, provider):
        from .leases import hold, session_name
        from .providers import execute_provider
        name = session_name(execution.tenant_id, execution.session_id)
        async with hold(settings.root, name):
            return await execute_provider(execution, settings, provider, journal=self.journal)

    async def reaper(self, active: dict) -> None:
        while True:
            await asyncio.sleep(30)
            await self.recover(set(active))
