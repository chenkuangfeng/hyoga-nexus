"""Skill rules on the platform side: publish immutable versions, resolve bindings, serve reads.

Functions take the caller's session. Publish functions open their own transaction, matching the
memory service; run-time reads are called inside the Run's transaction after the run owner is verified.
Denials are reported as ``NotFound`` so a skill that is not bound is indistinguishable from one that
does not exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.native import BUILTIN_TOOL_NAMES
from nexus_core.platform import SYSTEM_TENANT_ID, Principal, new_id, utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.authz.resources import authorize_resource
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound, PlatformError
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import (
    PlatformResourceRecord, ResourceBindingRecord, SessionSkillSnapshotRecord, SkillRecord,
    SkillVersionFileRecord, SkillVersionRecord,
)
from nexus_skills.guard import check_declared_scripts, static_hints
from nexus_skills.guard.scan import SCANNER_VERSION, ScanResult, scan_skill
from nexus_skills.policy import decide
from nexus_skills.loader import ScriptSpec, parse_skill
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


class SkillScanBlocked(InvalidConfiguration):
    """The scan result keeps a skill from being published; ``details`` carries the verdict and the findings."""

    def __init__(self, code: str, scan: ScanResult):
        super().__init__(code)
        self.code = code
        self.details = {'verdict': scan.verdict, 'scanner_version': scan.version, 'truncated': scan.truncated,
                        'findings': [{'rule': f.rule, 'severity': f.severity, 'category': f.category,
                                      'path': f.path, 'line': f.line, 'excerpt': f.excerpt}
                                     for f in scan.findings[:20]]}


#: Scan outcomes that stop a publish, as the stable error code returned to the caller.
_SCAN_STOPS = {'need_ack': 'skill_ack_required', 'block': 'skill_scan_blocked', 'refuse': 'skill_scan_refused',
               'review': 'skill_review_required'}


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
def publish(db: Session, principal: Principal, tenant_id: UUID, skill_md: str, files: dict[str, str],
            *, source: str = 'admin', acknowledge_findings: bool = False) -> dict[str, Any]:
    """Publish a new immutable version of a space skill; creates the skill on first publish.

    Checks, in order: administrator permission, SKILL.md rules, resource rules, declared scripts
    present, dependency tools known, a name already taken by a builtin skill, the scan against the release policy
    for ``source`` (``acknowledge_findings`` lets an administrator release a skill the policy would stop), a source
    conflict, and a change in content since the last version. The version is registered as a platform resource so
    bindings can name it.
    """
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, PUBLISH_PERMISSION)
        return _publish_version(db, tenant_id, user.id, skill_md, files, source, acknowledged=acknowledge_findings)


def _publish_version(db: Session, tenant_id: UUID, user_id: UUID, skill_md: str, files: dict[str, str],
                     source: str, *, acknowledged: bool = False) -> dict[str, Any]:
    """Publish inside the caller's transaction; the caller has already authorized the actor."""
    parsed = parse_skill(skill_md)
    if parsed.execution == 'local' and source != BUILTIN_SOURCE:
        raise InvalidConfiguration('skill_execution_not_permitted')
    clean = check_files(files)
    missing = check_declared_scripts(parsed, clean)
    if missing:
        raise InvalidConfiguration(missing[0])
    unknown = [tool for tool in parsed.tools if tool not in AVAILABLE_TOOL_NAMES]
    if unknown:
        raise InvalidConfiguration(f'skill_tool_unknown:{unknown[0]}')
    if tenant_id != SYSTEM_TENANT_ID and db.scalar(select(SkillRecord.id).where(
            SkillRecord.tenant_id == SYSTEM_TENANT_ID, SkillRecord.name == parsed.name).limit(1)) is not None:
        raise InvalidConfiguration('skill_name_taken_by_builtin')
    scan = scan_skill(skill_md, clean)
    decision = decide(source, scan.verdict, acknowledged=acknowledged)
    if decision != 'allow':
        raise SkillScanBlocked(_SCAN_STOPS[decision], scan)
    released = acknowledged and decide(source, scan.verdict) in ('need_ack', 'block')
    digest = content_hash(skill_md, clean)
    now = utc_now()
    skill = db.scalar(select(SkillRecord).where(SkillRecord.tenant_id == tenant_id, SkillRecord.name == parsed.name))
    if skill is None:
        skill = SkillRecord(id=new_id(), tenant_id=tenant_id, name=parsed.name, source=source,
                            created_by=user_id, created_at=now)
        db.add(skill)
        db.flush()
        number = 1
    else:
        if skill.source != source:
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
        scan_hints=hints, trust=source, scan_version=scan.version, scan=scan.as_dict(),
        model_invocable=parsed.model_invocable, user_invocable=parsed.user_invocable, execution=parsed.execution,
        extra={'values': parsed.extra, 'notes': list(parsed.notes)},
        content_hash=digest, created_by=user_id, created_at=now,
    )
    db.add(version)
    db.flush()
    for path, content in clean.items():
        db.add(SkillVersionFileRecord(version_id=version.id, path=path, content=content))
    db.add(PlatformResourceRecord(id=new_id(), tenant_id=tenant_id, kind=RESOURCE_KIND, resource_id=parsed.name,
                                  version_id=str(version.id), active=True, created_at=now))
    skill.current_version_id = version.id
    audit(db, tenant_id, user_id, 'skill.published', 'skill', str(skill.id),
          {'name': parsed.name, 'version': number, 'content_hash': digest, 'scan_hint_count': len(hints),
           'source': source, 'verdict': scan.verdict})
    if released:
        # The administrator released findings the policy would have stopped: record who, and what was released.
        audit(db, tenant_id, user_id, 'skill.findings_acknowledged', 'skill', str(skill.id),
              {'name': parsed.name, 'version': number, 'verdict': scan.verdict,
               'rules': sorted({f.rule for f in scan.findings})})
    return {'skill': parsed.name, 'version': number, 'version_id': str(version.id), 'content_hash': digest,
            'scan_hints': hints, 'verdict': scan.verdict, 'findings': len(scan.findings), 'notes': list(parsed.notes)}


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
    lines = [f'{name} | {version.description}' for name, version in sorted(bound_versions(db, agent_version_id).items())
             if version.model_invocable]
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
    if version is None or not version.model_invocable:
        raise NotFound('skill_unavailable')
    try:
        authorize_resource(db, tenant_id, RESOURCE_KIND, name, source_tenant_id=version.tenant_id,
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


@dataclass(frozen=True)
class PreparedScript:
    """Everything a script run needs, read inside the caller's transaction and then used outside it."""
    skill: str
    version: int
    version_id: str
    content_hash: str
    skill_md: str
    files: dict[str, str]
    spec: ScriptSpec


def prepare_script(db: Session, tenant_id: UUID, agent_version_id: UUID, name: str, script: str) -> PreparedScript:
    """Resolve a declared script of a bound skill version. Unbound or unknown scripts are NotFound.

    Only the version's own files are returned, so the working copy matches what was published.
    """
    version = bound_versions(db, agent_version_id).get(name)
    if version is None:
        raise NotFound('skill_unavailable')
    spec = next((item for item in parse_skill(version.skill_md).scripts if item.name == script), None)
    if spec is None:
        raise NotFound('skill_script_unavailable')
    try:
        authorize_resource(db, tenant_id, RESOURCE_KIND, name, source_tenant_id=version.tenant_id,
                           resource_version_id=str(version.id), permission='use')
    except PlatformError:
        raise NotFound('skill_unavailable') from None
    files = {row.path: row.content for row in db.scalars(select(SkillVersionFileRecord).where(
        SkillVersionFileRecord.version_id == version.id))}
    return PreparedScript(skill=name, version=version.version, version_id=str(version.id),
                          content_hash=version.content_hash, skill_md=version.skill_md, files=files, spec=spec)


def scripts_available(policy_flag: bool) -> bool:
    """Whether ``run_skill_script`` may be offered now: agent setting on, and the platform gate open.

    The gate is the configuration flag, the development auth mode and the local execution backend
    (proposal 2026-11-04-skill-scripts, section 6). Failing any one hides the tool.
    """
    from nexus_platform.configuration import auth_settings, skill_scripts_allowed, skill_scripts_gate
    return bool(policy_flag) and skill_scripts_gate(
        auth_mode=auth_settings().mode, backend=LOCAL_BACKEND, config_enabled=skill_scripts_allowed())


#: The only execution backend the scripts runner implements. Sandbox backends are not wired here.
LOCAL_BACKEND = 'local'


def list_skills(db: Session, principal: Principal, tenant_id: UUID) -> list[dict[str, Any]]:
    """Skills of the space plus the builtin skills, which every space can see and assign.

    Builtin entries carry ``scope = 'builtin'`` and ``disabled`` (the space switched them off: still listed so an
    administrator can switch them back on, but not assignable). Any active member may read the list.
    """
    context(db, principal, tenant_id)
    from nexus_platform.system import disabled_builtins
    off = disabled_builtins(db, tenant_id)
    rows = db.execute(select(SkillRecord, SkillVersionRecord).outerjoin(
        SkillVersionRecord, SkillVersionRecord.id == SkillRecord.current_version_id)
        .where(SkillRecord.tenant_id.in_((tenant_id, SYSTEM_TENANT_ID))).order_by(SkillRecord.name)).all()
    return [{'name': skill.name, 'source': skill.source, 'version': version.version if version else None,
             'description': version.description if version else '',
             'scope': 'builtin' if skill.tenant_id == SYSTEM_TENANT_ID else 'space',
             'source_tenant_id': str(skill.tenant_id),
             'disabled': skill.tenant_id == SYSTEM_TENANT_ID and ('skill', skill.name) in off}
            for skill, version in rows]


def skill_versions(db: Session, principal: Principal, tenant_id: UUID, name: str) -> list[dict[str, Any]]:
    """Version history of one skill: metadata, hashes and advisory hints. Bodies and files are not returned."""
    context(db, principal, tenant_id)
    skill = db.scalar(select(SkillRecord).where(SkillRecord.tenant_id == tenant_id, SkillRecord.name == name))
    if skill is None:
        skill = db.scalar(select(SkillRecord).where(SkillRecord.tenant_id == SYSTEM_TENANT_ID, SkillRecord.name == name))
    if skill is None:
        raise NotFound('skill_not_found')
    versions = db.scalars(select(SkillVersionRecord).where(SkillVersionRecord.skill_id == skill.id)
                          .order_by(SkillVersionRecord.version)).all()
    return [{'version': v.version, 'version_id': str(v.id), 'content_hash': v.content_hash, 'description': v.description,
             'tools': list(v.tools), 'scripts': [s['name'] for s in v.scripts], 'scan_hints': list(v.scan_hints),
             'trust': v.trust, 'verdict': (v.scan or {}).get('verdict', 'unscanned'),
             'findings': list((v.scan or {}).get('findings', [])), 'scan_version': v.scan_version,
             'rescan_needed': v.scan_version < SCANNER_VERSION,
             'model_invocable': v.model_invocable, 'user_invocable': v.user_invocable, 'execution': v.execution,
             'notes': list((v.extra or {}).get('notes', [])),
             'created_at': v.created_at.isoformat()} for v in versions]


def rescan(db: Session, principal: Principal, tenant_id: UUID, name: str, version: int) -> dict[str, Any]:
    """Scan one published version again with the current scanner and store the new result beside it.

    The version's content, hash and bindings do not change; only ``scan`` and ``scan_version`` are replaced.
    Needs ``tools:manage``. Use it after the scanner is upgraded (the list marks such versions ``rescan_needed``).
    """
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, PUBLISH_PERMISSION)
        skill = db.scalar(select(SkillRecord).where(SkillRecord.tenant_id == tenant_id, SkillRecord.name == name))
        row = None if skill is None else db.scalar(select(SkillVersionRecord).where(
            SkillVersionRecord.skill_id == skill.id, SkillVersionRecord.version == version))
        if row is None:
            raise NotFound('skill_not_found')
        files = {item.path: item.content for item in db.scalars(select(SkillVersionFileRecord).where(
            SkillVersionFileRecord.version_id == row.id))}
        result = scan_skill(row.skill_md, files)
        row.scan, row.scan_version = result.as_dict(), result.version
        audit(db, tenant_id, user.id, 'skill.rescanned', 'skill', str(skill.id),
              {'name': name, 'version': version, 'verdict': result.verdict, 'scanner_version': result.version})
        return {'skill': name, 'version': version, 'verdict': result.verdict, 'findings': len(result.findings),
                'scan_version': result.version}


#: Source label for skills imported from the repository's ``skills/`` directory.
BUILTIN_SOURCE = 'builtin'
#: Files that belong to the repository layout, not to a skill version.
_SKIP_NAMES = frozenset({'README.md'})


def read_skill_folder(folder: Path) -> tuple[str, dict[str, str]]:
    """Read SKILL.md and every other file under one skill folder as UTF-8 text, keyed by relative path."""
    skill_md = (folder / 'SKILL.md').read_text(encoding='utf-8')
    files: dict[str, str] = {}
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.name == 'SKILL.md' or path.name.startswith('.'):
            continue
        files[path.relative_to(folder).as_posix()] = path.read_text(encoding='utf-8')
    return skill_md, files


def import_builtin(db: Session, principal: Principal, root: Path) -> list[dict[str, Any]]:
    """Publish every skill folder under ``root`` (a folder holding SKILL.md) as a builtin skill of the system space.

    Only platform administrators may import. Builtin skills are assignable in every space. Folders whose content
    matches the current version are reported as ``unchanged`` instead of failing, so the import can be run again
    after each repository update; changed content becomes a new version, and agent versions that bound an earlier
    version keep it. Each folder is published in its own transaction, so one bad folder does not roll back the
    others; its error code is reported.
    """
    from nexus_platform.identity.service import resolve_user
    with db.begin():
        user = resolve_user(db, principal)
        if not user.is_platform_admin:
            raise Forbidden('platform_admin_required')
        admin_id = user.id
    return import_builtin_as(db, admin_id, root)


def import_builtin_as(db: Session, actor_id: UUID, root: Path) -> list[dict[str, Any]]:
    """The import itself, for callers that have already authorized the actor (the operator command, tests)."""
    from nexus_platform.system import ensure_system_tenant
    with db.begin():
        ensure_system_tenant(db)
    admin_id = actor_id
    results: list[dict[str, Any]] = []
    for skill_file in sorted(root.rglob('SKILL.md')):
        folder = skill_file.parent
        if folder.name in _SKIP_NAMES:
            continue
        label = folder.relative_to(root).as_posix()
        try:
            skill_md, files = read_skill_folder(folder)
            with db.begin():
                outcome = _publish_version(db, SYSTEM_TENANT_ID, admin_id, skill_md, files, BUILTIN_SOURCE)
            results.append({'folder': label, 'status': 'published', **outcome})
        except Conflict as exc:
            results.append({'folder': label, 'status': 'unchanged', 'error': str(exc)})
        except (PlatformError, SkillFormatError, SkillFileError, UnicodeDecodeError, OSError) as exc:
            results.append({'folder': label, 'status': 'failed', 'error': str(exc)})
    return results
