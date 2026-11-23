"""Cross-process execution locks on a shared workspace volume.

The lock file stays outside every sandbox mount. Kernel locks survive stale metadata and are released
on process death. Only a lock holder may execute or remove a container; recent release time preserves idle TTL.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path


def open_lock(root: Path, name: str):
    directory = root / '_execution_locks'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return os.fdopen(os.open(directory / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'r+b')


@asynccontextmanager
async def hold(root: Path, name: str):
    import fcntl
    stream = open_lock(root, name)
    try:
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(.05)
        stream.seek(0)
        stream.write(b'1')
        stream.flush()
        yield
    finally:
        os.utime(stream.fileno(), None)
        stream.close()


def try_reap(root: Path, name: str, idle_seconds: int):
    """Return an exclusively locked file only when no caller is active and its idle TTL elapsed."""
    import fcntl
    stream = open_lock(root, name)
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A new lock has no execution history; its empty size permits legacy orphan cleanup.
        if stream.read(1) and time.time() - os.fstat(stream.fileno()).st_mtime < idle_seconds:
            stream.close()
            return None
        return stream
    except BlockingIOError:
        stream.close()
        return None


def session_name(tenant_id: str, session_id: str) -> str:
    import hashlib
    return 'session-' + hashlib.sha256(f'{tenant_id}/{session_id}'.encode()).hexdigest()


@contextmanager
def mutation(root: Path, name: str):
    """Serialize host file mutations with cloud snapshot publication, blocking only the file worker thread."""
    import fcntl
    stream = open_lock(root, name)
    try:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield
    finally:
        stream.close()
