"""Virtual path handling: models name `/workspace/...` and `/outputs/...`; the host path stays hidden.

`resolve` maps a virtual path onto a host root and refuses anything that leaves it: `..`, NUL bytes,
other roots, and symbolic links whose target lies outside the root (checked on the real path, so a link
created by a command inside the sandbox cannot be followed out). The final check is by real path and then
the file is opened; a link swapped in between the two steps is a known race that the container boundary
(not this check) must contain.
"""
from __future__ import annotations

import os
from pathlib import Path

from nexus_core.sandbox import SandboxError, VIRTUAL_ROOTS


def split(virtual: str) -> tuple[str, list[str]]:
    """Return (root, parts) for a virtual path, or raise `sandbox_path_invalid`."""
    if not isinstance(virtual, str) or not virtual or '\x00' in virtual or len(virtual) > 1024:
        raise SandboxError('sandbox_path_invalid')
    if not virtual.startswith('/'):
        raise SandboxError('sandbox_path_invalid', 'paths must be absolute, for example /workspace/notes.txt')
    parts = [part for part in virtual.split('/') if part not in ('', '.')]
    if '..' in parts:
        raise SandboxError('sandbox_path_invalid')
    root = '/' + parts[0] if parts else ''
    if root not in VIRTUAL_ROOTS:
        raise SandboxError('sandbox_path_invalid', f'only {" and ".join(VIRTUAL_ROOTS)} are available')
    return root, parts[1:]


def resolve(virtual: str, roots: dict[str, Path], *, must_exist: bool = False) -> Path:
    """Host path for `virtual`, guaranteed to lie inside its root's real path."""
    root, parts = split(virtual)
    base = roots[root].resolve()
    target = base.joinpath(*parts)
    # Resolve through existing links; for a path that does not exist yet, check its nearest existing parent.
    probe = target
    while not os.path.lexists(probe) and probe != base:
        probe = probe.parent
    real = Path(os.path.realpath(probe))
    if real != base and base not in real.parents:
        raise SandboxError('sandbox_path_invalid')
    if os.path.lexists(target) and Path(os.path.realpath(target)) != base and base not in Path(os.path.realpath(target)).parents:
        raise SandboxError('sandbox_path_invalid')
    if must_exist and not os.path.lexists(target):
        raise SandboxError('sandbox_not_found')
    return target


def virtual_of(host: Path, roots: dict[str, Path]) -> str:
    """The virtual path of a host path under one of the roots (used to report results without host paths)."""
    for name, base in roots.items():
        base = base.resolve()
        try:
            relative = host.resolve().relative_to(base)
        except ValueError:
            continue
        return name + ('/' + relative.as_posix() if relative.parts else '')
    raise SandboxError('sandbox_path_invalid')
