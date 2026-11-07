"""Remote skill sources: turning what an administrator typed into something fetchable (S3 3.9).

Pure parsing, no network. Five kinds, each normalized to a download URL plus where in the archive the skill lives:

- ``github``: ``https://github.com/o/r[/tree/<ref>/<dir>]`` or ``github:o/r[/<dir>][@ref]`` (the repository zipball);
- ``gitlab``: ``https://gitlab.com/g/p[/-/tree/<ref>/<dir>]`` (the repository archive);
- ``skills.sh``: ``https://skills.sh/o/r/<skill>`` — a listing page that points at a GitHub repository; the skill is
  the folder named ``<skill>`` that holds a SKILL.md;
- ``registry``: ``clawhub:<slug>[@version]`` (the ClawHub download endpoint);
- ``direct``: any other ``https`` URL, fetched as a zip.

Whatever the kind, the result is only a request for an archive: the archive then goes through the same unpacking,
scanning and release policy as an upload, and the address through the shared egress check (`nexus_core.egress`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

REGISTRY_BASE = 'https://clawhub.ai/api/v1/download'
_SEGMENT = re.compile(r'^[A-Za-z0-9._-]{1,100}$')
_REF = re.compile(r'^[A-Za-z0-9._/-]{1,100}$')
_SLUG = re.compile(r'^[a-z0-9][a-z0-9._-]{0,99}$')
_VERSION = re.compile(r'^[A-Za-z0-9._+-]{1,40}$')


class SourceError(ValueError):
    """The input is not a source we can read; the message is the stable code ``skill_source_invalid``."""

    def __init__(self, detail: str = ''):
        super().__init__('skill_source_invalid')
        self.detail = detail


@dataclass(frozen=True)
class RemoteSource:
    """A normalized source. ``subdir`` narrows the archive to one folder; ``find_name`` finds the folder by name."""
    kind: str
    url: str
    subdir: str = ''
    find_name: str = ''
    ref: str = ''
    #: What the installer shows and records as the origin.
    label: str = ''

    def as_origin(self) -> dict[str, str]:
        return {'kind': self.kind, 'url': self.url, 'subdir': self.subdir, 'find_name': self.find_name,
                'ref': self.ref, 'label': self.label}


def _segments(*values: str) -> None:
    for value in values:
        if not value or value in ('.', '..') or not _SEGMENT.match(value):
            raise SourceError(f'bad segment {value[:40]!r}')


def _subdir(parts: list[str]) -> str:
    _segments(*parts)
    return '/'.join(parts)


def _github(owner: str, repo: str, ref: str, subdir: str, find: str = '') -> RemoteSource:
    repo = repo.removesuffix('.git')
    _segments(owner, repo)
    if ref and not _REF.match(ref):
        raise SourceError('bad ref')
    url = f'https://api.github.com/repos/{owner}/{repo}/zipball' + (f'/{quote(ref, safe="/")}' if ref else '')
    return RemoteSource('github', url, subdir=subdir, find_name=find, ref=ref,
                        label=f'github:{owner}/{repo}' + (f'/{subdir}' if subdir else '') + (f'@{ref}' if ref else ''))


def parse_source(text: str) -> RemoteSource:
    """Normalize a source string; raises :class:`SourceError` (code ``skill_source_invalid``) when it is not one."""
    value = (text or '').strip()
    if not value or len(value) > 500 or any(c.isspace() or ord(c) < 32 for c in value):
        raise SourceError('empty or malformed')
    if value.startswith('github:'):
        body, _, ref = value[len('github:'):].partition('@')
        parts = body.split('/')
        if len(parts) < 2:
            raise SourceError('github:owner/repo expected')
        return _github(parts[0], parts[1], ref, _subdir(parts[2:]) if parts[2:] else '')
    if value.startswith('clawhub:'):
        slug, _, version = value[len('clawhub:'):].partition('@')
        if not _SLUG.match(slug) or (version and not _VERSION.match(version)):
            raise SourceError('clawhub:slug[@version] expected')
        url = f'{REGISTRY_BASE}?slug={quote(slug)}' + (f'&version={quote(version)}' if version else '')
        return RemoteSource('registry', url, ref=version, label=f'clawhub:{slug}' + (f'@{version}' if version else ''))
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise SourceError('an https URL, github:… or clawhub:… expected')
    host = parsed.hostname.lower()
    path = [p for p in parsed.path.split('/') if p]
    if host in ('github.com', 'www.github.com'):
        if len(path) < 2:
            raise SourceError('github.com/owner/repo expected')
        if len(path) >= 4 and path[2] == 'tree':
            return _github(path[0], path[1], path[3], _subdir(path[4:]) if path[4:] else '')
        if len(path) == 2:
            return _github(path[0], path[1], '', '')
        raise SourceError('use a repository or /tree/<ref>/<dir> URL')
    if host == 'gitlab.com':
        marker = path.index('-') if '-' in path else len(path)
        project = path[:marker]
        if len(project) < 2:
            raise SourceError('gitlab.com/group/project expected')
        _segments(*project)
        ref, subdir = '', ''
        if marker < len(path):
            if len(path) < marker + 3 or path[marker + 1] != 'tree':
                raise SourceError('use a project or /-/tree/<ref>/<dir> URL')
            ref = path[marker + 2]
            subdir = _subdir(path[marker + 3:]) if path[marker + 3:] else ''
            if not _REF.match(ref):
                raise SourceError('bad ref')
        url = f'https://gitlab.com/api/v4/projects/{quote("/".join(project), safe="")}/repository/archive.zip'
        if ref:
            url += f'?sha={quote(ref, safe="")}'
        return RemoteSource('gitlab', url, subdir=subdir, ref=ref,
                            label=f'gitlab:{"/".join(project)}' + (f'/{subdir}' if subdir else ''))
    if host in ('skills.sh', 'www.skills.sh'):
        if len(path) != 3:
            raise SourceError('skills.sh/owner/repo/skill expected')
        _segments(*path)
        source = _github(path[0], path[1], '', '', find=path[2])
        return RemoteSource('skills.sh', source.url, find_name=path[2], label=f'skills.sh:{path[0]}/{path[1]}/{path[2]}')
    return RemoteSource('direct', value, label=value[:200])
