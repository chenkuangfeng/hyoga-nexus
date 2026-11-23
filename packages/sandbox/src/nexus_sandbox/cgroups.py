"""Optional cgroup v2 resource controller for bwrap command trees.

The operator delegates and enables cpu, memory and pids controllers on a dedicated parent. Nexus
creates only children of that parent and never changes the host's controller configuration.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from nexus_core.sandbox import SandboxError


class CommandCgroup:
    """Own CPU, memory and PID limits for a single command and all of its descendants."""

    def __init__(self, settings):
        self.path = None
        if not settings.cgroup_root:
            return
        parent = Path(settings.cgroup_root)
        try:
            if not {'cpu', 'memory', 'pids'} <= set((parent / 'cgroup.subtree_control').read_text().split()):
                raise ValueError
            path = parent / f'nexus-{uuid4().hex}'
            path.mkdir()
            self.path = path
            for key, value in {
                'cpu.max': f'{int(settings.cpus * 100000)} 100000',
                'memory.max': str(settings.memory_mb * 1024 * 1024),
                'memory.swap.max': '0',
                'pids.max': str(settings.pids),
            }.items():
                (path / key).write_text(value)
        except (OSError, ValueError):
            if self.path is not None:
                self.path.rmdir()
            raise SandboxError('sandbox_cgroup_unavailable') from None

    def wrap(self, argv: list[str]) -> list[str]:
        """Move the launcher into the delegated cgroup before executing bwrap."""
        if self.path is None:
            return argv
        return ['/bin/sh', '-ec', 'echo $$ > "$1/cgroup.procs"; shift; exec "$@"',
                'nexus-cgroup', str(self.path), *argv]

    async def close(self) -> None:
        """Kill any surviving descendants and remove the cgroup. Raise when cleanup is unconfirmed."""
        if self.path is None:
            return
        try:
            (self.path / 'cgroup.kill').write_text('1')
            for _ in range(100):
                if not (self.path / 'cgroup.procs').read_text().strip():
                    break
                await asyncio.sleep(.02)
            self.path.rmdir()
        except OSError:
            raise SandboxError('sandbox_cgroup_cleanup_failed') from None
