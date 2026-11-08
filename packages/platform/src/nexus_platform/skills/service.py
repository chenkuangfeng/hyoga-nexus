"""Skill rules on the platform side: publish immutable versions, resolve bindings, serve reads.

Functions take the caller's session. Publish functions open their own transaction, matching the
memory service; run-time reads are called inside the Run's transaction after the run owner is verified.
Denials are reported as ``NotFound`` so a skill that is not bound is indistinguishable from one that
does not exist.
"""
from __future__ import annotations

import re
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
    SkillUsageRecord, SkillVersionFileRecord, SkillVersionRecord,
)
from nexus_skills import bundle as skill_bundle
from nexus_skills.guard import check_declared_scripts, static_hints
from nexus_sandbox.build import has_manifest
from nexus_skills.verify import verify_files
from nexus_skills.exec import ResolvedScript, ScriptError, resolve_script
from nexus_skills.guard.scan import SCANNER_VERSION, ScanResult, scan_skill
from nexus_skills.policy import decide, resolve_execution
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
                     source: str, *, acknowledged: bool = False,
                     binary: dict[str, bytes] | None = None,
                     origin: dict[str, str] | None = None, profile: str | None = None,
                     owner_user_id: UUID | None = None, reviewed: bool = False) -> dict[str, Any]:
    """Publish inside the caller's transaction; the caller has already authorized the actor.

    ``binary`` holds the non-text files of a bundle; they live only in the version's zip and are projected into the
    sandbox beside the text files. The syntax check (`nexus_skills.verify`) runs before anything is stored.
    """
    binary = dict(binary or {})
    parsed = parse_skill(skill_md)
    if parsed.execution == 'local' and source != BUILTIN_SOURCE:
        raise InvalidConfiguration('skill_execution_not_permitted')
    clean = check_files(files)
    if set(binary) & set(clean):
        raise InvalidConfiguration('skill_path_duplicate')
    problems = [finding for finding in verify_files(clean) if finding.level == 'problem']
    if problems:
        raise InvalidConfiguration(f'skill_verify_failed:{problems[0].path}:{problems[0].message}')
    missing = check_declared_scripts(parsed, clean)
    if missing:
        raise InvalidConfiguration(missing[0])
    unknown = [tool for tool in parsed.tools if tool not in AVAILABLE_TOOL_NAMES]
    if unknown:
        raise InvalidConfiguration(f'skill_tool_unknown:{unknown[0]}')
    if tenant_id != SYSTEM_TENANT_ID and db.scalar(select(SkillRecord.id).where(
            SkillRecord.tenant_id == SYSTEM_TENANT_ID, SkillRecord.name == parsed.name).limit(1)) is not None:
        raise InvalidConfiguration('skill_name_taken_by_builtin')
    if owner_user_id is not None and db.scalar(select(SkillRecord.id).where(
            SkillRecord.tenant_id == tenant_id, SkillRecord.name == parsed.name,
            SkillRecord.owner_user_id.is_(None)).limit(1)) is not None:
        raise InvalidConfiguration('skill_name_taken_by_library')
    scan = scan_skill(skill_md, clean)
    decision = decide(source, scan.verdict, acknowledged=acknowledged)
    if decision == 'review' and reviewed:  # a person with tools:manage read it and approved it
        decision = 'allow'
    if decision != 'allow':
        raise SkillScanBlocked(_SCAN_STOPS[decision], scan)
    released = acknowledged and decide(source, scan.verdict) in ('need_ack', 'block')
    digest = content_hash(skill_md, clean, binary)
    packed = skill_bundle.pack(skill_md, clean, binary)
    now = utc_now()
    skill = db.scalar(select(SkillRecord).where(SkillRecord.tenant_id == tenant_id, SkillRecord.name == parsed.name,
                                                SkillRecord.owner_user_id.is_(owner_user_id) if owner_user_id is None
                                                else SkillRecord.owner_user_id == owner_user_id))
    if skill is None:
        skill = SkillRecord(id=new_id(), tenant_id=tenant_id, name=parsed.name, source=source,
                            owner_user_id=owner_user_id, created_by=user_id, created_at=now)
        db.add(skill)
        db.flush()
        number = 1
    else:
        if skill.source != source:
            raise InvalidConfiguration('skill_source_conflict')
        latest = db.scalar(select(SkillVersionRecord).where(SkillVersionRecord.skill_id == skill.id)
                           .order_by(SkillVersionRecord.version.desc()).limit(1))
        if db.scalar(select(SkillVersionRecord.id).where(SkillVersionRecord.skill_id == skill.id,
                                                         SkillVersionRecord.build_state == 'installing').limit(1)):
            raise Conflict('skill_install_in_progress')
        if latest is not None and latest.content_hash == digest and latest.build_state != 'failed':
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
        extra={'values': parsed.extra, 'notes': list(parsed.notes), **({'origin': origin} if origin else {})},
        content_hash=digest, bundle=packed, bundle_sha256=skill_bundle.digest(packed),
        created_by=user_id, created_at=now,
    )
    db.add(version)
    db.flush()
    for path, content in clean.items():
        db.add(SkillVersionFileRecord(version_id=version.id, path=path, content=content))
    installing = has_manifest(clean)
    if installing:
        # A dependency manifest means an environment must be built first; the version is not served until the
        # worker marks it ready (`nexus_platform.skills.install`). The pointer and the resource stay where they were.
        version.build_state = 'installing'
        version.extra = {**version.extra, 'install': {'profile': profile or ''}}
        audit(db, tenant_id, user_id, 'skill.install_started', 'skill', str(skill.id),
              {'name': parsed.name, 'version': number, 'content_hash': digest, 'source': source})
    else:
        activate(db, skill, version, user_id, scan_hints=len(hints))
    if released:
        # The administrator released findings the policy would have stopped: record who, and what was released.
        audit(db, tenant_id, user_id, 'skill.findings_acknowledged', 'skill', str(skill.id),
              {'name': parsed.name, 'version': number, 'verdict': scan.verdict,
               'rules': sorted({f.rule for f in scan.findings})})
    return {'skill': parsed.name, 'version': number, 'version_id': str(version.id), 'content_hash': digest,
            'scan_hints': hints, 'verdict': scan.verdict, 'findings': len(scan.findings), 'notes': list(parsed.notes),
            'binary_files': sorted(binary), 'build_state': version.build_state}


def library_skill(db: Session, tenant_id: UUID, name: str) -> SkillRecord | None:
    """The space-library (or builtin) skill of this name; private skills are never returned."""
    return db.scalar(select(SkillRecord).where(SkillRecord.tenant_id == tenant_id, SkillRecord.name == name,
                                               SkillRecord.owner_user_id.is_(None)))


def activate(db: Session, skill: SkillRecord, version: SkillVersionRecord, user_id: UUID, *, scan_hints: int = 0) -> None:
    """Make a version the one the skill serves: register it as a resource, move the pointer, record it.

    Runs at publish for a version without dependencies, and when the worker finishes building one that has them.
    """
    if skill.owner_user_id is None:  # a private skill is not a platform resource: it cannot be bound or granted
        db.add(PlatformResourceRecord(id=new_id(), tenant_id=version.tenant_id, kind=RESOURCE_KIND,
                                      resource_id=skill.name, version_id=str(version.id), active=True,
                                      created_at=utc_now()))
    skill.current_version_id = version.id
    version.build_state = 'ready'
    audit(db, version.tenant_id, user_id, 'skill.published', 'skill', str(skill.id),
          {'name': skill.name, 'version': version.version, 'content_hash': version.content_hash,
           'scan_hint_count': scan_hints, 'source': version.trust, 'verdict': (version.scan or {}).get('verdict')})


def install_bundle(db: Session, principal: Principal, tenant_id: UUID, data: bytes, *, source: str = 'import',
                   acknowledge_findings: bool = False, profile: str | None = None) -> dict[str, Any]:
    """Install a skill from an uploaded zip as a new version (administrators; source ``import`` by default).

    The archive is checked before anything is read (see `nexus_skills.bundle`), then goes through the same checks and
    release policy as a published skill, so an upload cannot do what a publish could not.
    """
    try:
        unpacked = skill_bundle.unpack(data)
    except skill_bundle.BundleError as exc:
        raise InvalidConfiguration(str(exc)) from None
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, PUBLISH_PERMISSION)
        return _publish_version(db, tenant_id, user.id, unpacked.skill_md, unpacked.text, source,
                                acknowledged=acknowledge_findings, binary=unpacked.binary, profile=profile)


def version_bundle(db: Session, version: SkillVersionRecord) -> bytes:
    """The zip of a version: the stored one, or one rebuilt from the file rows for versions older than bundles."""
    if version.bundle is not None:
        return version.bundle
    files = {row.path: row.content for row in db.scalars(select(SkillVersionFileRecord).where(
        SkillVersionFileRecord.version_id == version.id))}
    return skill_bundle.pack(version.skill_md, files)


def version_text_files(db: Session, version: SkillVersionRecord) -> dict[str, str]:
    """The text files of a version (not SKILL.md), keyed by path."""
    return {row.path: row.content for row in db.scalars(select(SkillVersionFileRecord).where(
        SkillVersionFileRecord.version_id == version.id))}


def _binary_files(db: Session, version: SkillVersionRecord, text_paths: set[str]) -> dict[str, bytes]:
    """Files of a version that are not text rows (they exist only in its zip)."""
    if version.bundle is None:
        return {}
    return {path: data for path, data in skill_bundle.read_entries(version.bundle).items()
            if path != 'SKILL.md' and path not in text_paths}


def export_bundle(db: Session, principal: Principal, tenant_id: UUID, name: str,
                  version: int | None = None) -> tuple[str, int, bytes]:
    """(skill name, version number, zip) of a skill visible in this space: its own, or a builtin one.

    Any member of the space may export; a version is a copy of what the space already uses. Defaults to the
    current version.
    """
    context(db, principal, tenant_id)
    skill = library_skill(db, tenant_id, name)
    if skill is None:
        skill = library_skill(db, SYSTEM_TENANT_ID, name)
    if skill is None:
        raise NotFound('skill_not_found')
    query = select(SkillVersionRecord).where(SkillVersionRecord.skill_id == skill.id)
    query = query.where(SkillVersionRecord.version == version) if version is not None else query.where(
        SkillVersionRecord.id == skill.current_version_id)
    row = db.scalar(query)
    if row is None:
        raise NotFound('skill_not_found')
    return name, row.version, version_bundle(db, row)


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


def usable_version(db: Session, tenant_id: UUID, agent_version_id: UUID, name: str,
                   user_id: UUID | None) -> tuple[SkillVersionRecord | None, bool]:
    """(version, is_private) of a skill a Run may use: one the agent version binds, else one of the user's own private
    skills. Private skills need no binding and no grant: being the owner is the authorization."""
    bound = bound_versions(db, agent_version_id).get(name)
    if bound is not None:
        return bound, False
    if user_id is not None:
        from nexus_platform.skills import private
        mine = private.visible_versions(db, tenant_id, user_id).get(name)
        if mine is not None:
            return mine, True
    return None, False


def record_use(db: Session, version: SkillVersionRecord, user_id: UUID, *, loaded: bool = True) -> None:
    """Note that a user's Run used a skill: ``loaded`` counts a ``load_skill``, otherwise only the time is refreshed
    (a script run). Never raises: a usage note must not break reading a skill."""
    from sqlalchemy.exc import SQLAlchemyError
    now = utc_now()
    try:
        with db.begin_nested():
            row = db.get(SkillUsageRecord, (version.skill_id, user_id))
            if row is None:
                db.add(SkillUsageRecord(skill_id=version.skill_id, user_id=user_id, last_used_at=now,
                                        use_count=1 if loaded else 0))
                db.flush()
            else:
                row.last_used_at = now
                if loaded:
                    row.use_count += 1
    except SQLAlchemyError:  # a concurrent first use of the same skill: the other writer's row is enough
        pass


def usage_totals(db: Session, skill_ids: list[UUID], user_id: UUID | None = None) -> dict[UUID, dict[str, Any]]:
    """skill id -> ``{use_count, last_used_at}``: one user's own numbers, or the sum over everyone when `user_id` is None."""
    if not skill_ids:
        return {}
    query = select(SkillUsageRecord.skill_id, func.sum(SkillUsageRecord.use_count), func.max(SkillUsageRecord.last_used_at)) \
        .where(SkillUsageRecord.skill_id.in_(skill_ids)).group_by(SkillUsageRecord.skill_id)
    if user_id is not None:
        query = query.where(SkillUsageRecord.user_id == user_id)
    return {skill_id: {'use_count': int(total or 0), 'last_used_at': last.isoformat() if last else None}
            for skill_id, total, last in db.execute(query)}


SEARCH_LIMIT = 10
_CJK = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+')


def _terms(text: str) -> set[str]:
    """Lower-case words, plus character pairs for CJK runs (which have no spaces to split on)."""
    lowered = text.lower()
    terms = {word for word in re.findall(r'\w+', _CJK.sub(' ', lowered)) if len(word) > 1}
    for run in _CJK.findall(lowered):
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            terms.add(run)
    return terms


def search_usable(db: Session, tenant_id: UUID, agent_version_id: UUID, user_id: UUID | None, query: str,
                  limit: int = SEARCH_LIMIT) -> list[tuple[str, str]]:
    """(name, description) of the skills this Run may use that match `query`, best first.

    Searches only skills the Run could load: the agent version's bound skills and the user's own private skills that are
    visible to the model. A name hit counts 3, a description hit 2, a body hit 1.
    """
    wanted = _terms(query)
    if not wanted:
        return []
    available = dict(bound_versions(db, agent_version_id))
    if user_id is not None:
        from nexus_platform.skills import private
        available.update({n: v for n, v in private.visible_versions(db, tenant_id, user_id).items() if n not in available})
    scored: list[tuple[int, str, str]] = []
    for name, version in available.items():
        if not version.model_invocable:
            continue
        name_terms, description_terms, body_terms = _terms(name.replace('-', ' ')), _terms(version.description), _terms(version.body)
        score = sum(3 for term in wanted if term in name_terms) + sum(2 for term in wanted if term in description_terms) \
            + sum(1 for term in wanted if term in body_terms)
        if score:
            scored.append((score, name, version.description))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(name, description) for _, name, description in scored[:max(1, min(limit, SEARCH_LIMIT))]]


def session_index(db: Session, tenant_id: UUID, session_id: UUID, agent_version_id: UUID,
                  user_id: UUID | None = None) -> str:
    """Name and description lines for the bound skills, frozen per session and agent version.

    The first Run stores the text; later Runs reuse it so the system prompt prefix does not change
    when skills are published. A different agent version recomputes and replaces the snapshot.
    """
    snapshot = db.get(SessionSkillSnapshotRecord, session_id)
    if snapshot is not None and snapshot.tenant_id == tenant_id and snapshot.agent_version_id == agent_version_id:
        return snapshot.index_text
    available = dict(bound_versions(db, agent_version_id))
    if user_id is not None:  # the owner's private skills join the index without being bound
        from nexus_platform.skills import private
        available.update({name: v for name, v in private.visible_versions(db, tenant_id, user_id).items()
                          if name not in available})
    lines = [f'{name} | {version.description}' for name, version in sorted(available.items())
             if version.model_invocable]
    text = '\n'.join(lines)
    if len(text) > INDEX_LIMIT:
        text = text[:INDEX_LIMIT].rsplit('\n', 1)[0] + '\n(more skills exist; find them with skill_search)'
    if snapshot is None:
        db.add(SessionSkillSnapshotRecord(session_id=session_id, tenant_id=tenant_id, agent_version_id=agent_version_id,
                                          index_text=text, created_at=utc_now()))
    else:
        snapshot.agent_version_id = agent_version_id
        snapshot.index_text = text
    return text


def read_for_run(db: Session, tenant_id: UUID, agent_version_id: UUID, name: str, path: str | None = None,
                 user_id: UUID | None = None) -> str:
    """Serve SKILL.md body (``path`` is None) or one resource file, for a model call inside a Run.

    The skill must be bound to the Run's agent version, and the version's resource grant is checked
    again here. Output is fenced as data so the body cannot close the wrapper or pose as a new message.
    """
    version, mine = usable_version(db, tenant_id, agent_version_id, name, user_id)
    if version is None or not version.model_invocable:
        raise NotFound('skill_unavailable')
    if not mine:
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
class PreparedExec:
    """Everything `exec_skill` needs, read inside the caller's transaction and then used outside it."""
    skill: str
    version: int
    version_id: str
    content_hash: str
    #: Where the version came from (``builtin`` / ``admin`` / ``import`` ...) and where its author meant it to run.
    source: str
    declared: str
    #: Every file of the version including SKILL.md, as projected into the sandbox.
    files: dict[str, str | bytes]
    script: ResolvedScript
    #: The version ships a dependency manifest, so its scripts need the environment built at install time.
    needs_env: bool = False


def prepare_exec(db: Session, tenant_id: UUID, agent_version_id: UUID, name: str, script: str,
                 user_id: UUID | None = None) -> PreparedExec:
    """Resolve a script of a bound skill version. Unbound, hidden or unknown skills and scripts are NotFound.

    Only the version's own files are returned, so what runs is what was published and scanned.
    """
    version, mine = usable_version(db, tenant_id, agent_version_id, name, user_id)
    if version is None or not version.model_invocable:
        raise NotFound('skill_unavailable')
    if not mine:
        try:
            authorize_resource(db, tenant_id, RESOURCE_KIND, name, source_tenant_id=version.tenant_id,
                               resource_version_id=str(version.id), permission='use')
        except PlatformError:
            raise NotFound('skill_unavailable') from None
    files = {row.path: row.content for row in db.scalars(select(SkillVersionFileRecord).where(
        SkillVersionFileRecord.version_id == version.id))}
    files['SKILL.md'] = version.skill_md
    try:
        resolved = resolve_script(script, files)  # text files only: a binary file is never a runnable script
    except ScriptError as exc:
        raise NotFound(str(exc)) from None
    files = {**files, **_binary_files(db, version, set(files))}
    return PreparedExec(skill=name, version=version.version, version_id=str(version.id), content_hash=version.content_hash,
                        source=version.trust, declared=version.execution, files=files, script=resolved,
                        needs_env=has_manifest(files))


def skill_files(db: Session, tenant_id: UUID, agent_version_id: UUID, name: str,
                user_id: UUID | None = None) -> tuple[str, dict[str, str | bytes]] | None:
    """(content hash, every file incl. SKILL.md) of a bound skill the model may use, or None when there is none."""
    version, _ = usable_version(db, tenant_id, agent_version_id, name, user_id)
    if version is None or not version.model_invocable:
        return None
    files = {row.path: row.content for row in db.scalars(select(SkillVersionFileRecord).where(
        SkillVersionFileRecord.version_id == version.id))}
    files['SKILL.md'] = version.skill_md
    return version.content_hash, {**files, **_binary_files(db, version, set(files))}


def exec_skill_available(policy_flag: bool, profile: str | None) -> bool:
    """Whether `exec_skill` may be offered to an agent: its setting is on and its sandbox profile is usable.

    The tool is not an arbitrary shell (a script of a bound skill, arguments not interpreted), so it does not wait for
    the agent to switch the whole `sandbox` group on; it does need a sandbox that passed acceptance, or a `local`
    profile in development mode.
    """
    if not policy_flag:
        return False
    from nexus_platform.runs.tool_gates import deployment_gate_facts
    facts = deployment_gate_facts(profile)
    return facts.sandbox_enabled and facts.sandbox_accepted


def sandbox_can_build(profile: str | None) -> bool:
    """Whether the chosen sandbox profile is usable, so a skill with scripts or dependencies can be made live."""
    from nexus_platform.runs.tool_gates import deployment_gate_facts
    facts = deployment_gate_facts(profile)
    return facts.sandbox_enabled and facts.sandbox_accepted


def execution_allowed(prepared: PreparedExec, profile: str | None) -> tuple[bool, str]:
    """Whether this skill's declared place to run fits the agent's profile, and the reason when it does not."""
    from nexus_platform.runs.tool_gates import deployment_gate_facts
    from nexus_sandbox.settings import load_config
    settings = load_config().get(profile)
    if settings is None:
        return False, 'sandbox_unavailable'
    return resolve_execution(prepared.declared, prepared.source, profile_type=settings.backend,
                             accepted=deployment_gate_facts(profile).sandbox_accepted,
                             allow_local_scripts=settings.allow_local_scripts)


def list_skills(db: Session, principal: Principal, tenant_id: UUID,
                sandbox_profile: str | None = None) -> list[dict[str, Any]]:
    """Skills of the space plus the builtin skills, which every space can see and assign.

    Builtin entries carry ``scope = 'builtin'`` and ``disabled`` (the space switched them off: still listed so an
    administrator can switch them back on, but not assignable). Any active member may read the list.

    With ``sandbox_profile`` (an empty string means the deployment's default profile) every skill that ships scripts
    also carries ``run``: ``{ok, reason}``, whether its scripts can run on that profile. The answer comes from the
    same rules ``exec_skill`` applies, so the editor can say so before a Run finds out.
    """
    context(db, principal, tenant_id)
    from nexus_platform.system import disabled_builtins
    off = disabled_builtins(db, tenant_id)
    rows = db.execute(select(SkillRecord, SkillVersionRecord).outerjoin(
        SkillVersionRecord, SkillVersionRecord.id == SkillRecord.current_version_id)
        .where(SkillRecord.tenant_id.in_((tenant_id, SYSTEM_TENANT_ID)), SkillRecord.owner_user_id.is_(None))
        .order_by(SkillRecord.name)).all()
    # Usage is shown for the space's own skills only: a builtin skill is used in every space, and its total would mix them.
    usage = usage_totals(db, [skill.id for skill, _ in rows if skill.tenant_id == tenant_id])
    fit = _script_fit(db, [version for _, version in rows if version is not None], sandbox_profile) \
        if sandbox_profile is not None else {}
    return [{'name': skill.name, 'source': skill.source, 'version': version.version if version else None,
             # What an agent binds: the version's id, and the tools the skill needs bound alongside it.
             'version_id': str(version.id) if version else None, 'tools': list(version.tools) if version else [],
             'execution': version.execution if version else 'sandbox',
             'model_invocable': version.model_invocable if version else True,
             # Whether the scripts can run on the asked-for profile; None for a skill without scripts.
             'run': fit.get(version.id) if version else None,
             'description': version.description if version else '',
             'verdict': (version.scan or {}).get('verdict', 'unscanned') if version else None,
             'rescan_needed': bool(version and version.scan_version < SCANNER_VERSION),
             'trust': version.trust if version else None,
             'use_count': usage.get(skill.id, {}).get('use_count', 0) if skill.tenant_id == tenant_id else None,
             'last_used_at': usage.get(skill.id, {}).get('last_used_at') if skill.tenant_id == tenant_id else None,
             'scope': 'builtin' if skill.tenant_id == SYSTEM_TENANT_ID else 'space',
             'source_tenant_id': str(skill.tenant_id),
             'disabled': skill.tenant_id == SYSTEM_TENANT_ID and ('skill', skill.name) in off}
            for skill, version in rows]


def _script_fit(db: Session, versions: list[SkillVersionRecord], profile: str) -> dict[UUID, dict[str, Any]]:
    """For each version that ships scripts: can they run on `profile`, and if not, why (a stable reason code)."""
    ids = [version.id for version in versions]
    scripted = set(db.scalars(select(SkillVersionFileRecord.version_id).where(
        SkillVersionFileRecord.version_id.in_(ids), SkillVersionFileRecord.path.like('scripts/%')))) if ids else set()
    if not scripted:
        return {}
    from nexus_core.deployment import DeploymentConfigError
    from nexus_platform.runs.tool_gates import deployment_gate_facts
    from nexus_sandbox.settings import load_config
    facts = deployment_gate_facts(profile)
    try:
        settings = load_config().get(profile)
    except DeploymentConfigError:
        settings = None
    result: dict[UUID, dict[str, Any]] = {}
    for version in versions:
        if version.id not in scripted:
            continue
        if not facts.sandbox_enabled:
            ok, reason = False, 'sandbox_disabled'
        elif settings is None:
            ok, reason = False, 'sandbox_profile_unknown'
        else:
            ok, reason = resolve_execution(version.execution, version.trust, profile_type=settings.backend,
                                           accepted=facts.sandbox_accepted,
                                           allow_local_scripts=settings.allow_local_scripts)
            if not ok and reason == 'sandbox_unavailable':
                reason = facts.sandbox_reason or 'sandbox_not_accepted'
        result[version.id] = {'ok': ok, 'reason': reason}
    return result


def skill_versions(db: Session, principal: Principal, tenant_id: UUID, name: str) -> list[dict[str, Any]]:
    """Version history of one skill: metadata, hashes and advisory hints. Bodies and files are not returned."""
    context(db, principal, tenant_id)
    skill = library_skill(db, tenant_id, name)
    if skill is None:
        skill = library_skill(db, SYSTEM_TENANT_ID, name)
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
             'notes': list((v.extra or {}).get('notes', [])), 'build_state': v.build_state,
             'has_bundle': v.bundle is not None, 'origin': (v.extra or {}).get('origin'), 'created_at': v.created_at.isoformat()} for v in versions]


def rescan(db: Session, principal: Principal, tenant_id: UUID, name: str, version: int) -> dict[str, Any]:
    """Scan one published version again with the current scanner and store the new result beside it.

    The version's content, hash and bindings do not change; only ``scan`` and ``scan_version`` are replaced.
    Needs ``tools:manage``. Use it after the scanner is upgraded (the list marks such versions ``rescan_needed``).
    """
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, PUBLISH_PERMISSION)
        skill = library_skill(db, tenant_id, name)
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
