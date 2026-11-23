"""Optional XFS project quotas for shell writes and inode exhaustion.

The operator provisions an XFS mount with project quotas and reserves an ID range for this deployment.
Nexus only assigns IDs within that range. Commands use argv directly and never invoke a host shell.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from nexus_core.sandbox import SandboxError
from .leases import mutation


def ensure(settings, session: Path) -> None:
    """Apply hard byte and inode limits to the whole session tree, or fail closed when configured."""
    if not settings.quota_mount:
        return
    session = session.resolve()
    mount = Path(settings.quota_mount).resolve()
    if mount not in session.parents or any(char.isspace() or char in "'\";" for char in str(session)):
        raise SandboxError('sandbox_disk_quota_invalid')
    registry = settings.root / '_quota_projects.json'
    try:
        with mutation(settings.root, 'quota-registry'):
            records = json.loads(registry.read_text()) if registry.exists() else {}
            entry = records.get(str(session))
            if entry is None:
                used = {value['id'] for value in records.values()}
                project = next((value for value in range(settings.quota_project_start,
                                                        settings.quota_project_start + 100000) if value not in used), None)
                if project is None:
                    raise ValueError
                entry = {'id': project, 'limits': None}
                records[str(session)] = entry
            limits = [settings.workspace_quota_mb, settings.quota_inodes]
            project = entry['id']
            # Persist the ID before assigning it in the filesystem, so a crash never reuses that ID.
            _save(registry, records)
            for command in (
                f'project -s -p {session} {project}',
                f'limit -p bhard={settings.workspace_quota_mb}m ihard={settings.quota_inodes} {project}',
            ):
                result = subprocess.run(['xfs_quota', '-x', '-c', command, str(mount)],
                                        stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
                if result.returncode or result.stderr:
                    raise ValueError
            entry['limits'] = limits
            _save(registry, records)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SandboxError('sandbox_disk_quota_unavailable') from None


def _save(target: Path, records: dict) -> None:
    with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(records, stream)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
