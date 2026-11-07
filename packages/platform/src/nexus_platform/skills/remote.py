"""Install a skill from a remote source (openspec 2026-11-07-skill-evolution, S3 3.9).

Administrators only, and only after an explicit confirmation: the address is fetched by this server. The source
string is normalized (`nexus_skills.source`), the archive is downloaded through the shared egress guard (public
addresses only, every redirect checked, a byte limit, a time limit), cut down to the one skill folder, and then goes
through exactly the path an uploaded zip takes: unpacking checks, syntax verification, scan and release policy. The
origin (kind, URL, ref, the archive digest) is recorded on the version so an update can be looked for later; an
update is never applied by itself.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core import egress
from nexus_core.platform import Principal
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.errors import Forbidden, InvalidConfiguration, NotFound, PlatformError
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import SkillRecord, SkillVersionRecord
from nexus_platform.skills import service
from nexus_skills import bundle as skill_bundle
from nexus_skills.source import RemoteSource, SourceError, parse_source
from nexus_skills.versions import content_hash

#: Download limits: the archive as served (not unpacked), and the wall clock for one fetch.
MAX_DOWNLOAD_BYTES = skill_bundle.MAX_UPLOAD_BYTES
DOWNLOAD_TIMEOUT = 300.0
#: Only the standard web ports: a skill source has no reason to live on 8080.
PORTS = (80, 443)
_STOPS = {'egress_url_invalid': 'skill_source_invalid', 'egress_destination_denied': 'skill_source_denied',
          'egress_unreachable': 'skill_source_unreachable', 'egress_timeout': 'skill_source_timeout',
          'egress_http_error': 'skill_source_http_error', 'egress_too_large': 'bundle_too_large',
          'egress_too_many_redirects': 'skill_source_unreachable'}


def _fetch(source: RemoteSource, *, transport=None, resolver=egress.default_resolver) -> bytes:
    """Download and return the archive of `source`. Runs the async guard to completion; called from sync code."""
    try:
        got = asyncio.run(egress.download(
            source.url, max_bytes=MAX_DOWNLOAD_BYTES, timeout=DOWNLOAD_TIMEOUT, ports=PORTS, on_oversize='error',
            headers={'User-Agent': 'HyogaNexus-SkillInstall/1.0', 'Accept': 'application/zip,*/*;q=0.5'},
            transport=transport, resolver=resolver))
    except egress.EgressError as exc:
        raise InvalidConfiguration(_STOPS.get(exc.code, 'skill_source_unreachable')) from None
    return got.body


def _prepare(source_text: str) -> RemoteSource:
    try:
        return parse_source(source_text)
    except SourceError:
        raise InvalidConfiguration('skill_source_invalid') from None


def _authorize(db: Session, principal: Principal, tenant_id: UUID) -> UUID:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, service.PUBLISH_PERMISSION)
        return user.id


def _archive(source: RemoteSource, fetch) -> tuple[skill_bundle.Bundle, str]:
    raw = fetch(source)
    try:
        cut = raw if source.kind == 'direct' and not (source.subdir or source.find_name) else skill_bundle.subtree(
            raw, subdir=source.subdir, find_name=source.find_name)
        return skill_bundle.unpack(cut), hashlib.sha256(raw).hexdigest()
    except skill_bundle.BundleError as exc:
        raise InvalidConfiguration(str(exc)) from None


def install_remote(db: Session, principal: Principal, tenant_id: UUID, source_text: str, *, confirm: bool,
                   acknowledge_findings: bool = False, fetch=None) -> dict[str, Any]:
    """Fetch the skill named by `source_text` and install it as a new version (source ``import``).

    `confirm` must be true: the caller has shown the administrator what will be fetched. `fetch` is a hook for
    tests (a function from a :class:`RemoteSource` to archive bytes).
    """
    if not confirm:
        raise InvalidConfiguration('skill_source_confirmation_required')
    source = _prepare(source_text)
    user_id = _authorize(db, principal, tenant_id)  # before any network traffic
    unpacked, archive_sha = _archive(source, fetch or _fetch)
    with db.begin():
        return service._publish_version(
            db, tenant_id, user_id, unpacked.skill_md, unpacked.text, 'import', acknowledged=acknowledge_findings,
            binary=unpacked.binary, origin={**source.as_origin(), 'archive_sha256': archive_sha})


def check_update(db: Session, principal: Principal, tenant_id: UUID, name: str, *, fetch=None) -> dict[str, Any]:
    """Whether the remote source of the installed skill now holds different content (nothing is changed)."""
    user_id = _authorize(db, principal, tenant_id)
    with db.begin():
        skill = service.library_skill(db, tenant_id, name)
        current = None if skill is None else db.get(SkillVersionRecord, skill.current_version_id)
        if current is None:
            raise NotFound('skill_not_found')
        origin = (current.extra or {}).get('origin')
        if not origin:
            raise InvalidConfiguration('skill_has_no_remote_source')
        installed_hash, number = current.content_hash, current.version
    del user_id
    source = RemoteSource(**{key: origin.get(key, '') for key in ('kind', 'url', 'subdir', 'find_name', 'ref', 'label')})
    unpacked, archive_sha = _archive(source, fetch or _fetch)
    from nexus_skills.versions import check_files
    fresh = content_hash(unpacked.skill_md, check_files(unpacked.text), unpacked.binary)
    return {'skill': name, 'installed_version': number, 'source': origin.get('label', ''),
            'update_available': fresh != installed_hash, 'archive_sha256': archive_sha}
