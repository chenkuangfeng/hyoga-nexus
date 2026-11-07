"""Skill bundles: reading an uploaded or downloaded zip safely, and writing the canonical zip of a version
(openspec 2026-11-07-skill-evolution, S3 3.3).

A zip comes from outside, so nothing in it is trusted. :func:`unpack` never touches the file system: it checks the
archive's entry table first (counts, declared sizes, names, symbolic links) and then reads each entry with a hard cap
on the bytes actually produced, so a header that lies about its size cannot turn into a decompression bomb. The
result is a :class:`Bundle`: the SKILL.md text, the UTF-8 text files, and the binary files (kept as bytes).

Layout rules: ``SKILL.md`` at the archive root, or inside the single top-level folder every entry shares (the shape
GitHub and most zip tools produce), in which case that folder is stripped. ``__MACOSX/``, ``.DS_Store`` and
dot-files are dropped. Everything else is kept under its canonical relative path.

:func:`pack` writes the canonical zip: entries sorted, fixed timestamps and permissions, deflate level fixed, so the
same content always gives the same bytes and :func:`digest` of the archive is stable.
"""
from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from dataclasses import dataclass, field

from ..versions import SkillFileError, normalize_path

#: Limits of one bundle. They are deliberately above the text-only publish limits: a bundle may carry images/fonts.
MAX_ENTRIES = 1000
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_UNPACKED_BYTES = 64 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024
#: Total / compressed above this is treated as a decompression bomb.
MAX_RATIO = 100
#: Text files beyond this are refused (the rest of the platform keeps text in database rows).
MAX_TEXT_BYTES = 64_000
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_IGNORED_NAMES = frozenset({'.DS_Store', 'Thumbs.db'})


class BundleError(SkillFileError):
    """The archive cannot be accepted; the message is a stable code (``bundle_*`` or a ``skill_path_*`` code)."""


@dataclass(frozen=True)
class Bundle:
    """The content of a bundle after checks. ``text`` excludes SKILL.md; ``binary`` holds non-UTF-8 files."""
    skill_md: str
    text: dict[str, str] = field(default_factory=dict)
    binary: dict[str, bytes] = field(default_factory=dict)
    #: Archive paths that were dropped (platform metadata, dot-files), for the install log.
    ignored: tuple[str, ...] = ()


def _is_link(info: zipfile.ZipInfo) -> bool:
    kind = stat.S_IFMT(info.external_attr >> 16)  # 0 when the writer recorded permissions only
    return kind not in (0, stat.S_IFREG, stat.S_IFDIR)  # symbolic links, devices, pipes, sockets


def _strip_root(names: list[str]) -> str:
    """The single top-level folder to strip, or ``''``. SKILL.md at the root wins over a wrapper folder."""
    if 'SKILL.md' in names:
        return ''
    tops = {name.split('/', 1)[0] for name in names if '/' in name}
    if len(tops) == 1 and all('/' in name for name in names) and f'{next(iter(tops))}/SKILL.md' in names:
        return next(iter(tops)) + '/'
    return ''


def unpack(data: bytes, *, max_upload: int = MAX_UPLOAD_BYTES) -> Bundle:
    """Validate and read a zip. Raises :class:`BundleError` with a stable code; reads nothing outside memory."""
    if len(data) > max_upload:
        raise BundleError('bundle_too_large')
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, EOFError, ValueError):
        raise BundleError('bundle_invalid') from None
    with archive:
        infos = [info for info in archive.infolist()]
        if len(infos) > MAX_ENTRIES:
            raise BundleError('bundle_too_many_entries')
        if any(info.flag_bits & 0x1 for info in infos):
            raise BundleError('bundle_encrypted')
        declared = sum(info.file_size for info in infos)
        compressed = sum(info.compress_size for info in infos) or 1
        if declared > MAX_UNPACKED_BYTES or any(info.file_size > MAX_ENTRY_BYTES for info in infos):
            raise BundleError('bundle_too_large_unpacked')
        if declared / compressed > MAX_RATIO and declared > 1024 * 1024:
            raise BundleError('bundle_ratio_suspicious')
        files = [info for info in infos if not info.is_dir()]
        for info in infos:
            if _is_link(info):
                raise BundleError('bundle_symlink')
        prefix = _strip_root([info.filename for info in files])
        ignored: list[str] = []
        seen: set[str] = set()
        text: dict[str, str] = {}
        binary: dict[str, bytes] = {}
        skill_md = None
        produced = 0
        for info in files:
            raw = info.filename
            if raw.startswith('__MACOSX/') or raw.split('/')[-1] in _IGNORED_NAMES:
                ignored.append(raw)
                continue
            if prefix and raw.startswith(prefix):
                raw = raw[len(prefix):]
            elif prefix:
                raise BundleError('bundle_layout')
            try:
                path = normalize_path(raw)  # rejects absolute, '..', backslash, NUL, over-long names
            except SkillFileError as exc:
                raise BundleError(str(exc)) from None
            if any(part.startswith('.') for part in path.split('/')):
                ignored.append(info.filename)
                continue
            if path in seen:
                raise BundleError('skill_path_duplicate')
            seen.add(path)
            with archive.open(info) as handle:
                content = handle.read(MAX_ENTRY_BYTES + 1)
            produced += len(content)
            if len(content) > MAX_ENTRY_BYTES or produced > MAX_UNPACKED_BYTES:
                raise BundleError('bundle_too_large_unpacked')
            if path == 'SKILL.md':
                try:
                    skill_md = content.decode('utf-8')
                except UnicodeDecodeError:
                    raise BundleError('bundle_skill_md_not_text') from None
                continue
            try:
                decoded = content.decode('utf-8')
            except UnicodeDecodeError:
                binary[path] = content
                continue
            if '\x00' in decoded:
                binary[path] = content
            elif len(content) > MAX_TEXT_BYTES:
                raise BundleError('skill_file_too_large')
            else:
                text[path] = decoded
        if skill_md is None:
            raise BundleError('bundle_skill_md_missing')
        return Bundle(skill_md=skill_md, text=dict(sorted(text.items())), binary=dict(sorted(binary.items())),
                      ignored=tuple(ignored))


def pack(skill_md: str, text: dict[str, str], binary: dict[str, bytes] | None = None) -> bytes:
    """The canonical zip of a version: sorted entries, fixed timestamps and modes, so equal content is equal bytes."""
    entries: dict[str, bytes] = {'SKILL.md': skill_md.encode('utf-8')}
    entries.update({path: content.encode('utf-8') for path, content in text.items()})
    entries.update(binary or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(entries):
            info = zipfile.ZipInfo(path, _FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, entries[path])
    return buffer.getvalue()


def digest(data: bytes) -> str:
    """SHA-256 of an archive."""
    return hashlib.sha256(data).hexdigest()


def read_entries(data: bytes) -> dict[str, bytes]:
    """Every entry of a canonical zip written by :func:`pack` (trusted: it came out of our own storage)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist() if not info.is_dir()}
