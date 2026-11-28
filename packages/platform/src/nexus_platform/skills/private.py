"""Private skills and their drafts (openspec 2026-11-07-skill-evolution, S4).

A private skill belongs to one user inside one space. Only that user's Runs see it; it is not a platform resource, so it
cannot be bound to an agent or granted to anyone. It is created through a *draft*: a mutable copy (SKILL.md plus text
files) that the model edits with ``skill_manage`` and the user then saves. Saving packs the draft into a zip and runs
it through the same checks, scan and build pipeline as an upload; the new version is live as soon as it is ready, and
every earlier version stays and can be returned to.

Functions here run inside the caller's transaction (the Run store's unit of work, or the API wrappers at the bottom)
and take already-authorized ``(tenant_id, user_id)``. Guards follow Hermes' skill manager: an edit needs the draft to
have been viewed in the same Run (``viewed`` is that set), a ``patch`` must match exactly once, attachments live only
under a few directories, and counts and sizes are capped.
"""
from __future__ import annotations

import posixpath
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import SYSTEM_TENANT_ID, Principal, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import SkillDraftRecord, SkillRecord, SkillVersionFileRecord, SkillVersionRecord
from nexus_platform.skills import service
from nexus_skills.lint import lint
from nexus_skills.loader import parse_skill
from nexus_skills.loader.frontmatter import SkillFormatError
from nexus_skills.versions import MAX_FILE_CHARS, SkillFileError, check_files, normalize_path

DRAFT_LIMIT = 20
PRIVATE_LIMIT = 50
TOTAL_BYTES = 4 * 1024 * 1024
ATTACHMENT_DIRS = ('refs/', 'scripts/', 'assets/', 'templates/')
PRIVATE_SOURCE = 'private'


def _parse(skill_md: str):
    try:
        return parse_skill(skill_md)
    except (SkillFormatError, SkillFileError) as exc:
        raise InvalidConfiguration(str(exc)) from None


def _attachment(path: str) -> str:
    try:
        clean = normalize_path(path)
    except SkillFileError as exc:
        raise InvalidConfiguration(str(exc)) from None
    if not clean.startswith(ATTACHMENT_DIRS) or posixpath.basename(clean).startswith('.'):
        raise InvalidConfiguration('skill_draft_path_not_allowed')
    return clean


def private_skill(db: Session, tenant_id: UUID, user_id: UUID, name: str) -> SkillRecord | None:
    return db.scalar(select(SkillRecord).where(SkillRecord.tenant_id == tenant_id, SkillRecord.owner_user_id == user_id,
                                               SkillRecord.name == name))


def _taken_elsewhere(db: Session, tenant_id: UUID, name: str) -> bool:
    """Whether the library or the builtin set already has a skill of this name."""
    return db.scalar(select(SkillRecord.id).where(
        SkillRecord.tenant_id.in_((tenant_id, SYSTEM_TENANT_ID)), SkillRecord.name == name,
        SkillRecord.owner_user_id.is_(None)).limit(1)) is not None


def _draft(db: Session, tenant_id: UUID, user_id: UUID, name: str) -> SkillDraftRecord:
    row = db.get(SkillDraftRecord, (tenant_id, user_id, name))
    if row is None:
        raise NotFound('skill_draft_not_found')
    return row


def _size(skill_md: str, files: dict[str, str]) -> int:
    return len(skill_md.encode('utf-8')) + sum(len(v.encode('utf-8')) for v in files.values())


def _check_total(db: Session, tenant_id: UUID, user_id: UUID, name: str, skill_md: str, files: dict[str, str]) -> None:
    others = sum(_size(d.skill_md, d.files) for d in db.scalars(select(SkillDraftRecord).where(
        SkillDraftRecord.tenant_id == tenant_id, SkillDraftRecord.owner_user_id == user_id,
        SkillDraftRecord.name != name)))
    if others + _size(skill_md, files) > TOTAL_BYTES:
        raise InvalidConfiguration('skill_draft_too_large')


def _require_read(name: str, viewed: set[str] | None) -> None:
    if viewed is not None and name not in viewed:
        raise InvalidConfiguration('skill_draft_unread')


def _report(row: SkillDraftRecord, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    parsed = _parse(row.skill_md)
    return {'name': row.name, 'files': sorted(row.files), 'lint': lint(parsed.description, parsed.body),
            **(extra or {})}


# ---------------------------------------------------------------------------------------------------- draft operations

def view(db: Session, tenant_id: UUID, user_id: UUID, name: str, path: str | None = None,
         viewed: set[str] | None = None) -> dict[str, Any]:
    """Return a draft's SKILL.md (or one attachment). With no draft but a private skill of this name, a draft is
    started from its current version, so editing an existing skill needs no separate step."""
    row = db.get(SkillDraftRecord, (tenant_id, user_id, name))
    if row is None:
        skill = private_skill(db, tenant_id, user_id, name)
        version = None if skill is None or skill.archived_at else db.get(SkillVersionRecord, skill.current_version_id)
        if version is None:
            raise NotFound('skill_draft_not_found')
        _check_count(db, tenant_id, user_id)
        files = {r.path: r.content for r in db.scalars(select(SkillVersionFileRecord).where(
            SkillVersionFileRecord.version_id == version.id))}
        row = SkillDraftRecord(tenant_id=tenant_id, owner_user_id=user_id, name=name, skill_md=version.skill_md,
                               files=files, base_hash=version.content_hash, updated_at=utc_now())
        db.add(row)
        db.flush()
    if viewed is not None:
        viewed.add(name)
    if path is None or path == 'SKILL.md':
        return {'name': name, 'path': 'SKILL.md', 'content': row.skill_md, 'files': sorted(row.files)}
    clean = _attachment(path)
    if clean not in row.files:
        raise NotFound('skill_draft_file_not_found')
    return {'name': name, 'path': clean, 'content': row.files[clean], 'files': sorted(row.files)}


def _check_count(db: Session, tenant_id: UUID, user_id: UUID) -> None:
    count = db.scalar(select(func.count()).select_from(SkillDraftRecord).where(
        SkillDraftRecord.tenant_id == tenant_id, SkillDraftRecord.owner_user_id == user_id))
    if count >= DRAFT_LIMIT:
        raise InvalidConfiguration('skill_draft_limit')


def create(db: Session, tenant_id: UUID, user_id: UUID, skill_md: str, files: dict[str, str] | None = None,
           viewed: set[str] | None = None) -> dict[str, Any]:
    """Start a new draft. The name comes from SKILL.md and must be free in the library, the builtin set and among the
    user's own skills and drafts."""
    parsed = _parse(skill_md)
    attachments = {_attachment(path): content for path, content in (files or {}).items()}
    try:
        check_files(attachments)
    except SkillFileError as exc:
        raise InvalidConfiguration(str(exc)) from None
    if _taken_elsewhere(db, tenant_id, parsed.name):
        raise InvalidConfiguration('skill_name_taken')
    if private_skill(db, tenant_id, user_id, parsed.name) is not None or db.get(
            SkillDraftRecord, (tenant_id, user_id, parsed.name)) is not None:
        raise Conflict('skill_draft_exists')
    _check_count(db, tenant_id, user_id)
    _check_total(db, tenant_id, user_id, parsed.name, skill_md, attachments)
    row = SkillDraftRecord(tenant_id=tenant_id, owner_user_id=user_id, name=parsed.name, skill_md=skill_md,
                           files=attachments, base_hash='', updated_at=utc_now())
    db.add(row)
    db.flush()
    if viewed is not None:
        viewed.add(parsed.name)
    return _report(row, {'created': True})


def _replace_once(text: str, old: str, new: str, replace_all: bool) -> str:
    if not old:
        raise InvalidConfiguration('skill_patch_empty')
    count = text.count(old)
    if count == 0:
        raise InvalidConfiguration('skill_patch_not_found')
    if count > 1 and not replace_all:
        raise InvalidConfiguration('skill_patch_ambiguous')
    return text.replace(old, new) if replace_all else text.replace(old, new, 1)


def patch(db: Session, tenant_id: UUID, user_id: UUID, name: str, old: str, new: str, path: str | None = None,
          replace_all: bool = False, viewed: set[str] | None = None) -> dict[str, Any]:
    """Replace `old` with `new` in SKILL.md or one attachment. `old` must match exactly once unless `replace_all`."""
    _require_read(name, viewed)
    row = _draft(db, tenant_id, user_id, name)
    if path is None or path == 'SKILL.md':
        updated = _replace_once(row.skill_md, old, new, replace_all)
        if _parse(updated).name != name:
            raise InvalidConfiguration('skill_name_immutable')
        _check_total(db, tenant_id, user_id, name, updated, row.files)
        row.skill_md = updated
    else:
        clean = _attachment(path)
        if clean not in row.files:
            raise NotFound('skill_draft_file_not_found')
        updated = _replace_once(row.files[clean], old, new, replace_all)
        _put_file(db, tenant_id, user_id, row, clean, updated)
    row.updated_at = utc_now()
    return _report(row)


def edit(db: Session, tenant_id: UUID, user_id: UUID, name: str, skill_md: str,
         viewed: set[str] | None = None) -> dict[str, Any]:
    """Replace the whole SKILL.md. The name cannot change (it is the skill's identity)."""
    _require_read(name, viewed)
    row = _draft(db, tenant_id, user_id, name)
    if _parse(skill_md).name != name:
        raise InvalidConfiguration('skill_name_immutable')
    _check_total(db, tenant_id, user_id, name, skill_md, row.files)
    row.skill_md, row.updated_at = skill_md, utc_now()
    return _report(row)


def _put_file(db: Session, tenant_id: UUID, user_id: UUID, row: SkillDraftRecord, path: str, content: str) -> None:
    files = {**row.files, path: content}
    if len(content) > MAX_FILE_CHARS:
        raise InvalidConfiguration('skill_file_too_large')
    try:
        check_files(files)
    except SkillFileError as exc:
        raise InvalidConfiguration(str(exc)) from None
    _check_total(db, tenant_id, user_id, row.name, row.skill_md, files)
    row.files = files  # a new dict, so the JSON column is seen as changed


def write_file(db: Session, tenant_id: UUID, user_id: UUID, name: str, path: str, content: str,
               viewed: set[str] | None = None) -> dict[str, Any]:
    """Create or replace one attachment under refs/, scripts/, assets/ or templates/."""
    _require_read(name, viewed)
    row = _draft(db, tenant_id, user_id, name)
    _put_file(db, tenant_id, user_id, row, _attachment(path), content)
    row.updated_at = utc_now()
    return _report(row)


def remove_file(db: Session, tenant_id: UUID, user_id: UUID, name: str, path: str,
                viewed: set[str] | None = None) -> dict[str, Any]:
    _require_read(name, viewed)
    row = _draft(db, tenant_id, user_id, name)
    clean = _attachment(path)
    if clean not in row.files:
        raise NotFound('skill_draft_file_not_found')
    row.files = {key: value for key, value in row.files.items() if key != clean}
    row.updated_at = utc_now()
    return _report(row)


def delete_draft(db: Session, tenant_id: UUID, user_id: UUID, name: str) -> dict[str, Any]:
    db.delete(_draft(db, tenant_id, user_id, name))
    return {'name': name, 'deleted': True}


# ---------------------------------------------------------------------------------------------------- saving

def save(db: Session, tenant_id: UUID, user_id: UUID, name: str, *, profile: str | None = None) -> dict[str, Any]:
    """Turn a draft into a new version of the private skill and make it live (after the build, if it has one).

    Refused: a dangerous scan, a base that moved since the draft started (``skill_base_changed``), and scripts or a
    dependency manifest when the chosen sandbox profile cannot run them. Bytes of binary files the draft never
    touched come over from the previous version unchanged.
    """
    draft = _draft(db, tenant_id, user_id, name)
    skill = private_skill(db, tenant_id, user_id, name)
    current = db.get(SkillVersionRecord, skill.current_version_id) if skill and skill.current_version_id else None
    if skill is not None and skill.archived_at is not None:
        raise Conflict('skill_archived')
    if (current.content_hash if current else '') != draft.base_hash:
        raise Conflict('skill_base_changed')
    if skill is None and db.scalar(select(func.count()).select_from(SkillRecord).where(
            SkillRecord.tenant_id == tenant_id, SkillRecord.owner_user_id == user_id,
            SkillRecord.archived_at.is_(None))) >= PRIVATE_LIMIT:
        raise InvalidConfiguration('skill_private_limit')
    if _taken_elsewhere(db, tenant_id, name):
        raise InvalidConfiguration('skill_name_taken')
    needs_sandbox = service.has_manifest(draft.files) or any(path.startswith('scripts/') for path in draft.files)
    if needs_sandbox and not service.sandbox_can_build(db, profile):
        raise InvalidConfiguration('skill_sandbox_required')
    binary = service._binary_files(db, current, set(draft.files)) if current is not None else {}
    try:
        result = service._publish_version(db, tenant_id, user_id, draft.skill_md, dict(draft.files), PRIVATE_SOURCE,
                                          binary=binary, profile=profile, owner_user_id=user_id)
    except Conflict as exc:
        if str(exc) == 'skill_version_unchanged':
            db.delete(draft)
            return {'skill': name, 'unchanged': True}
        raise
    db.delete(draft)
    parsed = _parse(draft.skill_md)
    return {**result, 'lint': lint(parsed.description, parsed.body)}


# ---------------------------------------------------------------------------------------------------- versions

def _owned(db: Session, tenant_id: UUID, user_id: UUID, name: str) -> SkillRecord:
    skill = private_skill(db, tenant_id, user_id, name)
    if skill is None:
        raise NotFound('skill_not_found')
    return skill


def versions(db: Session, tenant_id: UUID, user_id: UUID, name: str) -> list[dict[str, Any]]:
    skill = _owned(db, tenant_id, user_id, name)
    rows = db.scalars(select(SkillVersionRecord).where(SkillVersionRecord.skill_id == skill.id)
                      .order_by(SkillVersionRecord.version)).all()
    return [{'version': v.version, 'version_id': str(v.id), 'content_hash': v.content_hash, 'build_state': v.build_state,
             'build_error': v.build_error, 'verdict': (v.scan or {}).get('verdict', 'unscanned'),
             'current': v.id == skill.current_version_id, 'created_at': v.created_at.isoformat()} for v in rows]


def rollback(db: Session, tenant_id: UUID, user_id: UUID, name: str, version: int) -> dict[str, Any]:
    """Point the skill back at an earlier (or later) ready version. Nothing is deleted."""
    skill = _owned(db, tenant_id, user_id, name)
    row = db.scalar(select(SkillVersionRecord).where(SkillVersionRecord.skill_id == skill.id,
                                                     SkillVersionRecord.version == version))
    if row is None:
        raise NotFound('skill_version_not_found')
    if row.build_state != 'ready':
        raise Conflict('skill_version_not_ready')
    skill.current_version_id = row.id
    audit(db, tenant_id, user_id, 'skill.rolled_back', 'skill', str(skill.id), {'name': name, 'version': version})
    return {'skill': name, 'version': version}


def archive(db: Session, tenant_id: UUID, user_id: UUID, name: str) -> dict[str, Any]:
    skill = _owned(db, tenant_id, user_id, name)
    skill.archived_at = utc_now()
    audit(db, tenant_id, user_id, 'skill.archived', 'skill', str(skill.id), {'name': name})
    return {'skill': name, 'archived': True}


def restore(db: Session, tenant_id: UUID, user_id: UUID, name: str) -> dict[str, Any]:
    skill = _owned(db, tenant_id, user_id, name)
    skill.archived_at = None
    audit(db, tenant_id, user_id, 'skill.restored', 'skill', str(skill.id), {'name': name})
    return {'skill': name, 'archived': False}


def listing(db: Session, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    """The user's private skills and drafts. A skill whose name the library or builtin set now uses is
    ``superseded``: the library skill answers to that name and the private one is no longer offered."""
    taken = {name for name in db.scalars(select(SkillRecord.name).where(
        SkillRecord.tenant_id.in_((tenant_id, SYSTEM_TENANT_ID)), SkillRecord.owner_user_id.is_(None)))}
    skills = []
    owned = list(db.scalars(select(SkillRecord).where(SkillRecord.tenant_id == tenant_id,
                                                      SkillRecord.owner_user_id == user_id).order_by(SkillRecord.name)))
    usage = service.usage_totals(db, [skill.id for skill in owned], user_id)
    for skill in owned:
        version = db.get(SkillVersionRecord, skill.current_version_id) if skill.current_version_id else None
        latest = db.scalar(select(SkillVersionRecord).where(SkillVersionRecord.skill_id == skill.id)
                           .order_by(SkillVersionRecord.version.desc()).limit(1))
        skills.append({'name': skill.name, 'version': version.version if version else None,
                       'description': version.description if version else '',
                       'verdict': (version.scan or {}).get('verdict') if version else None,
                       'model_invocable': version.model_invocable if version else True,
                       'archived': skill.archived_at is not None, 'superseded': skill.name in taken,
                       'latest_version': latest.version if latest else None,
                       'latest_state': latest.build_state if latest else None,
                       'latest_error': latest.build_error if latest else None,
                       'use_count': usage.get(skill.id, {}).get('use_count', 0),
                       'last_used_at': usage.get(skill.id, {}).get('last_used_at'),
                       'created_at': skill.created_at.isoformat()})
    drafts = [{'name': d.name, 'files': sorted(d.files), 'updated_at': d.updated_at.isoformat(),
               'editing': bool(d.base_hash)}
              for d in db.scalars(select(SkillDraftRecord).where(
                  SkillDraftRecord.tenant_id == tenant_id, SkillDraftRecord.owner_user_id == user_id)
                  .order_by(SkillDraftRecord.name))]
    return {'skills': skills, 'drafts': drafts}


def visible_versions(db: Session, tenant_id: UUID, user_id: UUID) -> dict[str, SkillVersionRecord]:
    """name -> current version of the private skills a Run of this user may use: not archived, ready, not superseded."""
    taken = {name for name in db.scalars(select(SkillRecord.name).where(
        SkillRecord.tenant_id.in_((tenant_id, SYSTEM_TENANT_ID)), SkillRecord.owner_user_id.is_(None)))}
    return {name: version for name, version in db.execute(select(SkillRecord.name, SkillVersionRecord)
        .join(SkillVersionRecord, SkillVersionRecord.id == SkillRecord.current_version_id)
        .where(SkillRecord.tenant_id == tenant_id, SkillRecord.owner_user_id == user_id,
               SkillRecord.archived_at.is_(None), SkillVersionRecord.build_state == 'ready')) if name not in taken}



# ---------------------------------------------------------------------------------------------------- API wrappers

def as_member(db: Session, principal: Principal, tenant_id: UUID) -> UUID:
    """The caller's user id after the membership check (any active member may keep private skills)."""
    user, _ = context(db, principal, tenant_id)
    return user.id


def run_as_member(db: Session, principal: Principal, tenant_id: UUID, fn, *args, **kwargs):
    """Run one of the functions above for the calling member inside its own transaction (the API's entry)."""
    with db.begin():
        return fn(db, tenant_id, as_member(db, principal, tenant_id), *args, **kwargs)
