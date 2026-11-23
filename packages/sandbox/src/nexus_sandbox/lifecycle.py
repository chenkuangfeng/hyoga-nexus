"""Persistent gateway execution journal and cancellation-resistant cleanup.

Records contain IDs and policy hashes, never commands, tokens or user file contents. The state directory
is private to the gateway. A process lock makes restart recovery safe for a single execution-node owner.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from nexus_core.sandbox import SandboxError


async def drain(task):
    """Finish a cleanup task even if the caller receives repeated cancellation."""
    if not isinstance(task, asyncio.Task):
        task = asyncio.ensure_future(task)
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


class Journal:
    """Atomic request state with exclusive ownership of one gateway state directory."""

    def __init__(self, root: Path):
        import fcntl

        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = root
        self._lock = (root / '.owner').open('a')
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise SandboxError('sandbox_gateway_already_running') from None

    def close(self) -> None:
        self._lock.close()

    def _completed(self, request_id: str) -> Path:
        return self.root / '.completed' / request_id[:2] / f'{request_id}.json'

    def get(self, request_id: str) -> dict | None:
        try:
            completed = self._completed(request_id)
            source = completed if completed.exists() else self.root / f'{request_id}.json'
            return json.loads(source.read_text())
        except FileNotFoundError:
            return None

    def write(self, request_id: str, **changes) -> dict:
        record = self.get(request_id) or {'id': request_id, 'created_at': time.time()}
        record.update(changes, updated_at=time.time())
        target = (self._completed(request_id) if record.get('state') in ('finished', 'cancelled')
                  else self.root / f'{request_id}.json')
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=self.root, delete=False) as stream:
            name = Path(stream.name)
            try:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(name, target)
                if target.parent != self.root:
                    (self.root / f'{request_id}.json').unlink(missing_ok=True)
            finally:
                name.unlink(missing_ok=True)
        return record

    def pending(self) -> list[dict]:
        return [record for file in self.root.glob('*.json')
                if (record := json.loads(file.read_text())).get('state') not in ('finished', 'cancelled')]

    def reserve(self, request_id: str, profile: str) -> None:
        if self.get(request_id) is not None:
            raise SandboxError('sandbox_execution_already_exists')
        self.write(request_id, profile=profile, state='creating', sandbox_id=None)
