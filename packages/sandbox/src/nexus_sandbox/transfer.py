"""Bounded session snapshots, shared with the standalone provider runner.

This module uses only the Python standard library so the gateway can upload it into an ordinary Linux
template. Links and special files are rejected before publication. Files are read through directory
descriptors so a command cannot redirect a snapshot reader outside the selected root.
"""
from __future__ import annotations

import io
import os
import shutil
import stat
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

MAX_FILES = 4096
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
ROOTS = ('workspace', 'outputs')


@contextmanager
def directory(path: Path):
    """Open a directory without following any symbolic-link component."""
    descriptor = os.open(path.anchor or '.', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts:
            if part in (path.anchor, '.', ''):
                continue
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        yield descriptor
    finally:
        os.close(descriptor)


def pack(roots: dict[str, Path], target: Path, *, limit: int = MAX_TOTAL_BYTES) -> None:
    """Write a bounded uncompressed archive of regular files and directories."""
    count = total = 0

    def visit(archive, descriptor, prefix):
        nonlocal count, total
        for name in sorted(os.listdir(descriptor)):
            count += 1
            if count > MAX_FILES or len(PurePosixPath(prefix, name).parts) > 32:
                raise ValueError('snapshot file count or depth exceeded')
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            relative = str(PurePosixPath(prefix, name))
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    entry = tarfile.TarInfo(relative)
                    entry.type, entry.mode = tarfile.DIRTYPE, 0o755
                    archive.addfile(entry)
                    visit(archive, child, relative)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                with os.fdopen(handle, 'rb') as stream:
                    actual = os.fstat(stream.fileno())
                    if not stat.S_ISREG(actual.st_mode) or actual.st_size > MAX_FILE_BYTES:
                        raise ValueError('snapshot file invalid')
                    total += actual.st_size
                    if total > limit:
                        raise ValueError('snapshot bytes exceeded')
                    entry = tarfile.TarInfo(relative)
                    entry.size = actual.st_size
                    entry.mode = 0o755 if actual.st_mode & 0o111 else 0o644
                    archive.addfile(entry, stream)
            else:
                raise ValueError('snapshot links and special files are forbidden')

    with tarfile.open(target, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for name, root in roots.items():
            if name not in (*ROOTS, 'skills'):
                raise ValueError('snapshot root invalid')
            with directory(root) as descriptor:
                entry = tarfile.TarInfo(name)
                entry.type, entry.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(entry)
                visit(archive, descriptor, name)


def unpack(source: Path, destination: Path, *, roots: tuple[str, ...] = ROOTS,
           limit: int = MAX_TOTAL_BYTES) -> None:
    """Validate and extract into a new, private staging directory, never into a live workspace."""
    # Reject extension headers before tarfile can allocate a hostile PAX/GNU metadata payload.
    with source.open('rb') as raw:
        entries = 0
        while header := raw.read(512):
            if not header.strip(b'\0'):
                break
            entries += 1
            if len(header) != 512 or header[156:157] not in (b'0', b'\0', b'5') or entries > MAX_FILES + len(roots):
                raise ValueError('snapshot header invalid')
            try:
                size = int(header[124:136].strip(b'\0 ') or b'0', 8)
            except ValueError:
                raise ValueError('snapshot size invalid') from None
            if size < 0 or size > MAX_FILE_BYTES:
                raise ValueError('snapshot file too large')
            raw.seek((size + 511) // 512 * 512, io.SEEK_CUR)
    count = total = 0
    seen = set()
    with tarfile.open(source, 'r:') as archive:
        for entry in archive:
            count += 1
            name = PurePosixPath(entry.name)
            if (count > MAX_FILES + len(roots) or entry.name in seen or name.is_absolute()
                    or '..' in name.parts or not name.parts or name.parts[0] not in roots
                    or len(name.parts) > 32 or '\\' in entry.name or '\x00' in entry.name
                    or not (entry.isdir() or entry.isreg()) or entry.size < 0 or entry.size > MAX_FILE_BYTES):
                raise ValueError('snapshot entry invalid')
            seen.add(entry.name)
            total += entry.size
            if total > limit:
                raise ValueError('snapshot bytes exceeded')
            target = destination.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.isdir():
                target.mkdir(exist_ok=True)
            else:
                stream = archive.extractfile(entry)
                if stream is None:
                    raise ValueError('snapshot content missing')
                with stream, target.open('xb') as output:
                    shutil.copyfileobj(stream, output, 65536)
                target.chmod(0o755 if entry.mode & 0o111 else 0o644)
    if not all((destination / root).is_dir() for root in roots):
        raise ValueError('snapshot roots missing')


def publish(source: Path, base: Path, *, limit: int = MAX_TOTAL_BYTES) -> None:
    """Validate the full snapshot, then replace roots with rollback on publication failure."""
    recover_publication(base)
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=base) as temporary:
        staging = Path(temporary)
        unpack(source, staging, limit=limit)
        (staging / '.publication').write_text('prepared')
        replaced = []
        try:
            with directory(base) as base_fd, directory(staging) as stage_fd:
                for root in ROOTS:
                    backup = f'old-{root}'
                    os.rename(root, backup, src_dir_fd=base_fd, dst_dir_fd=stage_fd)
                    try:
                        os.rename(root, root, src_dir_fd=stage_fd, dst_dir_fd=base_fd)
                    except BaseException:
                        os.rename(backup, root, src_dir_fd=stage_fd, dst_dir_fd=base_fd)
                        raise
                    replaced.append(root)
                os.fsync(base_fd)
                with (staging / '.publication').open('w') as marker:
                    marker.write('committed')
                    marker.flush()
                    os.fsync(marker.fileno())
        except BaseException:
            for root in reversed(replaced):
                shutil.rmtree(base / root)
                os.replace(staging / f'old-{root}', base / root)
            raise


def recover_publication(base: Path) -> None:
    """Roll back interrupted root replacements. Call only while holding the session's mutation lock."""
    for staging in base.glob('.sync-*'):
        marker = staging / '.publication'
        if staging.is_symlink() or not marker.is_file():
            continue
        if marker.read_text() != 'committed':
            for root in ROOTS:
                backup = staging / f'old-{root}'
                if not backup.exists():
                    continue
                target = base / root
                if target.is_symlink():
                    target.unlink()
                elif target.exists():
                    shutil.rmtree(target)
                os.replace(backup, target)
        shutil.rmtree(staging)
