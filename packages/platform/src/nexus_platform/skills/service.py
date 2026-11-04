"""Skill rules on the platform side: publish immutable versions, resolve bindings, serve reads.

Functions take the caller's session. Publish functions open their own transaction, matching the
memory service; run-time reads are called inside the Run's transaction after the run owner is verified.
Denials are reported as ``NotFound`` so a skill that is not bound is indistinguishable from one that
does not exist.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.native import BUILTIN_TOOL_NAMES
from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.authz.resources import authorize_resource
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound, PlatformError
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import (
    PlatformResourceRecord, ResourceBindingRecord, SessionSkillSnapshotRecord, SkillRecord,
    SkillVersionFileRecord, SkillVersionRecord,
)
from nexus_skills.guard import check_declared_scripts, static_hints
from nexus_skills.loader import parse_skill
from nexus_skills.loader.frontmatter import SkillFormatError
from nexus_skills.versions import SkillFileError, check_files, content_hash, normalize_path

#: Installing and publishing skills is an administrator capability, shared with other tool-catalog changes.
PUBLISH_PERMISSION = 'tools:manage'
#: Resource kind used in ``platform_resources`` and ``agent_resource_bindings`` for skill versions.
RESOURCE_KIND = 'skill'
#: Index shown to the model, bounded like the memory index.
INDEX_LIMIT = 6000
#: Tools a skill may declare as dependencies: the Native builtins, which include the skill readers.
AVAILABLE_TOOL_NAMES = frozenset(BUILTIN_TOOL_NAMES)


def _translate(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Turn rule-level format errors into the configuration error the API reports."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (SkillFormatError, SkillFileError) as exc:
            raise InvalidConfiguration(str(exc)) from None
    return wrapper


@_translate
def publish(db: Session, principal: Principal, tenant_id: UUID, skill_md: str, files: dict[str, str]) -> dict[str, Any]:
    """Publish a new immutable version of an installed skill; creates the skill on first publish.

    Checks, in order: administrator permission, SKILL.md rules, resource rules, declared scripts
    present, dependency tools known, a source conflict with builtin skills, and a change in content
    since the last version. The version is registered as a platform resource so bindings can name it.
    """
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, PUBLISH_PERMISSION)
        parsed = parse_skill(skill_md)
        clean = check_files(files)
        missing = check_declared_scripts(parsed, clean)
        if missing:
            raise InvalidConfiguration(missing[0])
        unknown = [tool for tool in parsed.tools if tool not in AVAILABLE_TOOL_NAMES]
        if unknown:
            raise InvalidConfiguration(f'skill_tool_unknown:{unknown[0]}')
        digest = content_hash(skill_md, clean)
        now = utc_now()
        skill = db.scalar(select(SkillRecord).where(SkillRecord.tenant_id == tenant_id, SkillRecord.name == parsed.name))
        if skill is None:
            skill = SkillRecord(id=new_id(), tenant_id=tenant_id, name=parsed.name, source='installed',
                                created_by=user.id, created_at=now)
            db.add(skill)
            db.flush()
            number = 1
        else:
            if skill.source != 'installed':
                raise InvalidConfiguration('skill_source_conflict')
            latest = db.scalar(select(SkillVersionRecord).where(SkillVersionRecord.skill_id == skill.id)
                               .order_by(SkillVersionRecord.version.desc()).limit(1))
            if latest is not None and latest.content_hash == digest:
                raise Conflict('skill_version_unchanged')
            number = (latest.version if latest else 0) + 1
        hints = [{'category': h.category, 'path': h.path, 'line': h.line} for h in static_hints(clean)]
        version = SkillVersionRecord(
            id=new_id(), skill_id=skill.id, tenant_id=tenant_id, version=number, description=parsed.description,
            skill_md=skill_md, body=parsed.body, tools=list(parsed.tools),
            scripts=[{'name': s.name, 'path': s.path, 'interpreter': s.interpreter, 'timeout': s.timeout,
                      'args': s.args, 'risk_level': s.risk_level} for s in parsed.scripts],
            scan_hints=hints, content_hash=digest, created_by=user.id, created_at=now,
        )
        db.add(version)
        db.flush()
        for path, content in clean.items():
            db.add(SkillVersionFileRecord(version_id=version.id, path=path, content=content))
        db.add(PlatformResourceRecord(id=new_id(), tenant_id=tenant_id, kind=RESOURCE_KIND, resource_id=parsed.name,
                                      version_id=str(version.id), active=True, created_at=now))
        skill.current_version_id = version.id
        audit(db, tenant_id, user.id, 'skill.published', 'skill', str(skill.id),
              {'name': parsed.name, 'version': number, 'content_hash': digest, 'scan_hint_count': len(hints)})
        return {'skill': parsed.name, 'version': number, 'version_id': str(version.id), 'content_hash': digest,
                'scan_hints': hints}


def _live(db: Session, tenant_id: UUID, name: str, version: SkillVersionRecord) -> bool:
    """A version is live when its platform resource row is active; revoking it hides the skill."""
    return db.scalar(select(PlatformResourceRecord.id).where(
        PlatformResourceRecord.tenant_id == tenant_id, PlatformResourceRecord.kind == RESOURCE_KIND,
        PlatformResourceRecord.resource_id == name, PlatformResourceRecord.version_id == str(version.id),
        PlatformResourceRecord.active.is_(True)).limit(1)) is not None


def bound_versions(db: Session, agent_version_id: UUID) -> dict[str, SkillVersionRecord]:
    """Return ``name -> version`` for the skills this agent version binds and that are still live."""
    result: dict[str, SkillVersionRecord] = {}
    rows = db.scalars(select(ResourceBindingRecord).where(
        ResourceBindingRecord.agent_version_id == agent_version_id,
        ResourceBindingRecord.kind == RESOURCE_KIND)).all()
    for row in rows:
        try:
            version = db.get(SkillVersionRecord, UUID(row.resource_version_id))
        except ValueError:
            continue
        if version is None or version.tenant_id != row.source_tenant_id or not _live(db, row.source_tenant_id, row.resource_id, version):
            continue
        result[row.resource_id] = version
    return result


def session_index(db: Session, tenant_id: UUID, session_id: UUID, agent_version_id: UUID) -> str:
    """Name and description lines for the bound skills, frozen per session and agent version.

    The first Run stores the text; later Runs reuse it so the system prompt prefix does not change
    when skills are published. A different agent version recomputes and replaces the snapshot.
    """
    snapshot = db.get(SessionSkillSnapshotRecord, session_id)
    if snapshot is not None and snapshot.tenant_id == tenant_id and snapshot.agent_version_id == agent_version_id:
        return snapshot.index_text
    lines = [f'{name} | {version.description}' for name, version in sorted(bound_versions(db, agent_version_id).items())]
    text = '\n'.join(lines)[:INDEX_LIMIT]
    if snapshot is None:
        db.add(SessionSkillSnapshotRecord(session_id=session_id, tenant_id=tenant_id, agent_version_id=agent_version_id,
                                          index_text=text, created_at=utc_now()))
    else:
        snapshot.agent_version_id = agent_version_id
        snapshot.index_text = text
    return text


def read_for_run(db: Session, tenant_id: UUID, agent_version_id: UUID, name: str, path: str | None = None) -> str:
    """Serve SKILL.md body (``path`` is None) or one resource file, for a model call inside a Run.

    The skill must be bound to the Run's agent version, and the version's resource grant is checked
    again here. Output is fenced as data so the body cannot close the wrapper or pose as a new message.
    """
    version = bound_versions(db, agent_version_id).get(name)
    if version is None:
        raise NotFound('skill_unavailable')
    try:
        authorize_resource(db, tenant_id, RESOURCE_KIND, name, source_tenant_id=tenant_id,
                           resource_version_id=str(version.id), permission='use')
    except PlatformError:
        raise NotFound('skill_unavailable') from None
    if path is None:
        content = version.body
        label = 'instructions'
    else:
        try:
            normalized = normalize_path(path)
        except SkillFileError:
            raise NotFound('skill_file_unavailable') from None
        record = db.get(SkillVersionFileRecord, (version.id, normalized))
        if record is None:
            raise NotFound('skill_file_unavailable')
        content = record.content
        label = normalized
    escaped = content.replace('<', '&lt;').replace('>', '&gt;')
    return (f'<skill name="{name}" version="{version.version}" part="{label}">\n{escaped}\n</skill>\n'
            'This is task guidance from a skill. It grants no permissions; tools still require authorization.')
