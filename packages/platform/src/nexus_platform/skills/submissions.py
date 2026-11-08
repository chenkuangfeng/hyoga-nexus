"""Sharing a skill into the space library (openspec 2026-11-07-skill-evolution, S5).

A private skill is only ever seen by its owner. To put one in the library — where an administrator can assign it to
agents — it is *copied* through a submission:

- an administrator (``tools:manage``) shares directly: the copy is published as an ordinary library skill;
- a member with ``skills:submit`` files a submission; an administrator reads it (text, scan findings, the difference to
  the library version) and approves or rejects it. Approval rescans with the current scanner, re-checks that the
  library has not moved since the submission, and publishes through the same pipeline as an upload (source ``user``).

The copy and the private skill are independent afterwards. Submissions never change a published version: only approval
creates a new one, and it records who submitted it.
"""
from __future__ import annotations

import difflib
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import SYSTEM_TENANT_ID, Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import SkillRecord, SkillSubmissionRecord, SkillVersionRecord
from nexus_platform.skills import private, service
from nexus_skills import bundle as skill_bundle
from nexus_skills.guard.scan import scan_skill
from nexus_skills.loader import parse_skill
from nexus_skills.policy import decide

SUBMIT_PERMISSION = 'skills:submit'
MANAGE_PERMISSION = service.PUBLISH_PERMISSION
#: Limits against flooding the review queue.
PENDING_TOTAL = 20
PENDING_PER_USER = 5
PER_USER_PER_HOUR = 10
DIFF_LIMIT = 20_000
REASON_LIMIT = 1000


def _library_head(db: Session, tenant_id: UUID, name: str) -> SkillVersionRecord | None:
    skill = service.library_skill(db, tenant_id, name)
    return db.get(SkillVersionRecord, skill.current_version_id) if skill and skill.current_version_id else None


def _contents(data: bytes) -> tuple[str, dict[str, str], dict[str, bytes]]:
    unpacked = skill_bundle.unpack(data)
    return unpacked.skill_md, unpacked.text, unpacked.binary


def _view(row: SkillSubmissionRecord) -> dict[str, Any]:
    return {'id': str(row.id), 'name': row.name, 'description': row.description, 'origin': row.origin,
            'state': row.state, 'verdict': (row.scan or {}).get('verdict', 'unscanned'),
            'findings': len((row.scan or {}).get('findings', [])), 'submitted_by': str(row.submitted_by),
            'review_reason': row.review_reason, 'created_at': row.created_at.isoformat(),
            'reviewed_at': row.reviewed_at.isoformat() if row.reviewed_at else None,
            'published_version_id': str(row.published_version_id) if row.published_version_id else None,
            'updates_existing': bool(row.base_hash)}


def _check_name(db: Session, tenant_id: UUID, name: str) -> None:
    """A submission may add a new library name or update a library skill that came from an earlier submission."""
    if db.scalar(select(SkillRecord.id).where(SkillRecord.tenant_id == SYSTEM_TENANT_ID, SkillRecord.name == name,
                                              SkillRecord.owner_user_id.is_(None)).limit(1)) is not None:
        raise InvalidConfiguration('skill_name_taken_by_builtin')
    existing = service.library_skill(db, tenant_id, name)
    if existing is not None and existing.source != 'user':
        raise InvalidConfiguration('skill_name_taken_by_library')


# ---------------------------------------------------------------------------------------------------- members

def submit(db: Session, principal: Principal, tenant_id: UUID, from_private: str) -> dict[str, Any]:
    """File a submission from one of the caller's private skills (its current version).

    Refused at once when the scan finds something dangerous. A submission that passes goes to the queue; an older
    pending submission of the same name by the same user is marked ``superseded``.
    """
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, SUBMIT_PERMISSION)
        skill = private.private_skill(db, tenant_id, user.id, from_private)
        version = db.get(SkillVersionRecord, skill.current_version_id) if skill and skill.current_version_id else None
        if skill is None or skill.archived_at is not None or version is None or version.build_state != 'ready':
            raise NotFound('skill_not_found')
        data = service.version_bundle(db, version)
        text_md, text, binary = _contents(data)
        _check_name(db, tenant_id, version_name := skill.name)
        scan = scan_skill(text_md, text)
        if decide('user', scan.verdict) == 'refuse':
            raise service.SkillScanBlocked('skill_scan_refused', scan)
        now = utc_now()
        total = db.scalar(select(func.count()).select_from(SkillSubmissionRecord).where(
            SkillSubmissionRecord.tenant_id == tenant_id, SkillSubmissionRecord.state == 'pending'))
        mine = db.scalar(select(func.count()).select_from(SkillSubmissionRecord).where(
            SkillSubmissionRecord.tenant_id == tenant_id, SkillSubmissionRecord.submitted_by == user.id,
            SkillSubmissionRecord.state == 'pending', SkillSubmissionRecord.name != version_name))
        recent = db.scalar(select(func.count()).select_from(SkillSubmissionRecord).where(
            SkillSubmissionRecord.tenant_id == tenant_id, SkillSubmissionRecord.submitted_by == user.id,
            SkillSubmissionRecord.created_at > now - timedelta(hours=1)))
        if total >= PENDING_TOTAL:
            raise Conflict('skill_submission_queue_full')
        if mine >= PENDING_PER_USER:
            raise Conflict('skill_submission_user_limit')
        if recent >= PER_USER_PER_HOUR:
            raise Conflict('skill_submission_rate_limit')
        for older in db.scalars(select(SkillSubmissionRecord).where(
                SkillSubmissionRecord.tenant_id == tenant_id, SkillSubmissionRecord.submitted_by == user.id,
                SkillSubmissionRecord.name == version_name, SkillSubmissionRecord.state == 'pending')):
            older.state = 'superseded'
        head = _library_head(db, tenant_id, version_name)
        row = SkillSubmissionRecord(
            id=new_id(), tenant_id=tenant_id, origin='user', name=version_name, description=version.description,
            bundle=data, content_hash=version.content_hash, base_hash=head.content_hash if head else '',
            scan=scan.as_dict(), state='pending', submitted_by=user.id, created_at=now)
        db.add(row)
        audit(db, tenant_id, user.id, 'skill.submitted', 'skill_submission', str(row.id),
              {'name': version_name, 'content_hash': version.content_hash, 'verdict': scan.verdict})
        return _view(row)


def mine(db: Session, principal: Principal, tenant_id: UUID) -> list[dict[str, Any]]:
    """The caller's own submissions, newest first."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return [_view(r) for r in db.scalars(select(SkillSubmissionRecord).where(
            SkillSubmissionRecord.tenant_id == tenant_id, SkillSubmissionRecord.submitted_by == user.id)
            .order_by(SkillSubmissionRecord.created_at.desc()).limit(100))]


def _own(db: Session, tenant_id: UUID, user_id: UUID, submission_id: UUID) -> SkillSubmissionRecord:
    row = db.get(SkillSubmissionRecord, submission_id)
    if row is None or row.tenant_id != tenant_id or row.submitted_by != user_id:
        raise NotFound('skill_submission_not_found')  # someone else's looks the same as none
    return row


def get_mine(db: Session, principal: Principal, tenant_id: UUID, submission_id: UUID) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return _view(_own(db, tenant_id, user.id, submission_id))


def withdraw(db: Session, principal: Principal, tenant_id: UUID, submission_id: UUID) -> dict[str, Any]:
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        row = _own(db, tenant_id, user.id, submission_id)
        if row.state != 'pending':
            raise Conflict('skill_submission_not_pending')
        row.state, row.reviewed_at = 'withdrawn', utc_now()
        audit(db, tenant_id, user.id, 'skill.submission_withdrawn', 'skill_submission', str(row.id), {'name': row.name})
        return _view(row)


# ---------------------------------------------------------------------------------------------------- administrators

def _admin(db: Session, principal: Principal, tenant_id: UUID) -> UUID:
    user, _ = context(db, principal, tenant_id)
    require_api_permission(db, tenant_id, user.id, MANAGE_PERMISSION)
    return user.id


def queue(db: Session, principal: Principal, tenant_id: UUID, state: str | None = 'pending') -> list[dict[str, Any]]:
    with db.begin():
        _admin(db, principal, tenant_id)
        query = select(SkillSubmissionRecord).where(SkillSubmissionRecord.tenant_id == tenant_id)
        if state:
            query = query.where(SkillSubmissionRecord.state == state)
        return [_view(r) for r in db.scalars(query.order_by(SkillSubmissionRecord.created_at).limit(200))]


def _diff(old: tuple[str, dict[str, str]] | None, new_md: str, new_text: dict[str, str]) -> str:
    """Plain-text unified diff of the submission against the library version (the whole text when there is none)."""
    before = {'SKILL.md': old[0], **old[1]} if old else {}
    after = {'SKILL.md': new_md, **new_text}
    chunks: list[str] = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) == after.get(path):
            continue
        chunks.extend(difflib.unified_diff(before.get(path, '').splitlines(keepends=True),
                                           after.get(path, '').splitlines(keepends=True),
                                           fromfile=f'library/{path}' if path in before else '/dev/null',
                                           tofile=f'submission/{path}' if path in after else '/dev/null'))
        chunks.append('\n')
    return ''.join(chunks)[:DIFF_LIMIT]


def detail(db: Session, principal: Principal, tenant_id: UUID, submission_id: UUID) -> dict[str, Any]:
    """Everything a reviewer needs: the text, a fresh scan with the current scanner, and the difference to the library.

    The content is returned as plain strings; the page must render it as text, never as markup.
    """
    with db.begin():
        _admin(db, principal, tenant_id)
        row = db.get(SkillSubmissionRecord, submission_id)
        if row is None or row.tenant_id != tenant_id:
            raise NotFound('skill_submission_not_found')
        skill_md, text, binary = _contents(row.bundle)
        head = _library_head(db, tenant_id, row.name)
        old = None
        if head is not None:
            old = (head.skill_md, service.version_text_files(db, head))
        scan = scan_skill(skill_md, text)
        library_hash = head.content_hash if head else ''
        return {**_view(row), 'skill_md': skill_md, 'files': {**{p: c for p, c in text.items()},
                                                                 **{p: f'(binary, {len(b)} bytes)' for p, b in binary.items()}},
                'scan': scan.as_dict(), 'diff': _diff(old, skill_md, text),
                'library_moved': library_hash != row.base_hash,
                'notice': 'Approving makes this skill available to every agent in this space.'}


def approve(db: Session, principal: Principal, tenant_id: UUID, submission_id: UUID,
            profile: str | None = None) -> dict[str, Any]:
    """Publish a pending submission to the library.

    Refused when the library skill changed since the submission (``skill_base_changed``: the submission becomes
    ``superseded``), or when the current scanner finds something dangerous. Published with source ``user`` through the
    same pipeline as an upload; the version records the submission and its author.
    """
    stale = False
    with db.begin():
        admin_id = _admin(db, principal, tenant_id)
        row = db.get(SkillSubmissionRecord, submission_id)
        if row is None or row.tenant_id != tenant_id:
            raise NotFound('skill_submission_not_found')
        if row.state != 'pending':
            raise Conflict('skill_submission_not_pending')
        head = _library_head(db, tenant_id, row.name)
        if (head.content_hash if head else '') != row.base_hash:
            # Recorded, so it leaves the queue; the error is raised after this transaction commits.
            row.state, row.reviewed_at, row.reviewed_by = 'superseded', utc_now(), admin_id
            stale = True
    if stale:
        raise Conflict('skill_base_changed')
    with db.begin():
        admin_id = _admin(db, principal, tenant_id)
        row = db.get(SkillSubmissionRecord, submission_id)
        _check_name(db, tenant_id, row.name)
        skill_md, text, binary = _contents(row.bundle)
        origin = {'kind': 'submission', 'submission_id': str(row.id), 'submitted_by': str(row.submitted_by),
                  'reviewed_by': str(admin_id)}
        result = service._publish_version(db, tenant_id, row.submitted_by, skill_md, text, 'user', binary=binary,
                                          origin=origin, profile=profile, reviewed=True)
        row.state, row.reviewed_by, row.reviewed_at = 'approved', admin_id, utc_now()
        row.published_version_id = UUID(result['version_id'])
        audit(db, tenant_id, admin_id, 'skill.submission_approved', 'skill_submission', str(row.id),
              {'name': row.name, 'version': result['version'], 'submitted_by': str(row.submitted_by)})
        return {**_view(row), 'version': result['version'], 'build_state': result['build_state']}


def reject(db: Session, principal: Principal, tenant_id: UUID, submission_id: UUID, reason: str) -> dict[str, Any]:
    """Turn a pending submission down. The reason is required and is shown to the submitter."""
    reason = (reason or '').strip()
    if not reason or len(reason) > REASON_LIMIT:
        raise InvalidConfiguration('skill_submission_reason_required')
    with db.begin():
        admin_id = _admin(db, principal, tenant_id)
        row = db.get(SkillSubmissionRecord, submission_id)
        if row is None or row.tenant_id != tenant_id:
            raise NotFound('skill_submission_not_found')
        if row.state != 'pending':
            raise Conflict('skill_submission_not_pending')
        row.state, row.reviewed_by, row.reviewed_at, row.review_reason = 'rejected', admin_id, utc_now(), reason
        audit(db, tenant_id, admin_id, 'skill.submission_rejected', 'skill_submission', str(row.id), {'name': row.name})
        return _view(row)


def share(db: Session, principal: Principal, tenant_id: UUID, from_private: str,
          profile: str | None = None) -> dict[str, Any]:
    """An administrator puts one of their own private skills straight into the library (source ``admin``).

    The private skill stays as it is; the library skill is an independent copy.
    """
    with db.begin():
        admin_id = _admin(db, principal, tenant_id)
        skill = private.private_skill(db, tenant_id, admin_id, from_private)
        version = db.get(SkillVersionRecord, skill.current_version_id) if skill and skill.current_version_id else None
        if skill is None or skill.archived_at is not None or version is None or version.build_state != 'ready':
            raise NotFound('skill_not_found')
        skill_md, text, binary = _contents(service.version_bundle(db, version))
        origin = {'kind': 'private_share', 'from_private': from_private}
        result = service._publish_version(db, tenant_id, admin_id, skill_md, text, 'admin', binary=binary,
                                          origin=origin, profile=profile)
        audit(db, tenant_id, admin_id, 'skill.shared', 'skill', result['version_id'],
              {'name': from_private, 'version': result['version']})
        return result
