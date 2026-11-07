"""Building a skill version's dependencies and bringing it into service (openspec 2026-11-07-skill-evolution, S3 3.4/3.7).

A version with a dependency manifest is stored as ``installing`` (see `service._publish_version`); the worker picks it
up here. One build is a sequence of steps, and any step that fails leaves the previously served version in place:

1. claim the row (``build_heartbeat_at`` set; one worker wins);
2. build the environment in a private staging directory (`nexus_sandbox.build`, the profile's temporary environment,
   network on, limits on time, output and size);
3. verification gate: the packages named in ``requirements.txt`` must appear in what the build reported installed;
4. swap the environment in with one ``rename`` into the profile's environment root;
5. in one transaction: ``ready``, the pointer moves, the version is registered as a resource, audit.

``failed`` keeps the stored zip, so `reinstall` retries without anyone uploading again. A heartbeat is written at
every step; a row whose heartbeat stops (a worker that died) is failed by `reap`, which also removes leftover staging
directories, orphaned build containers and environments no ready version refers to any more.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from nexus_core.platform import utc_now
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Conflict, InvalidConfiguration, NotFound
from nexus_platform.models.provider_settings import context
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.persistence.models import SkillRecord, SkillVersionFileRecord, SkillVersionRecord
from nexus_platform.skills import service
from nexus_sandbox import build
from nexus_sandbox.settings import SandboxSettings, load_config
from nexus_skills.verify import missing_distributions, parse_requirements

logger = logging.getLogger('nexus_platform.skills.install')

#: A build whose heartbeat is older than this has lost its worker.
STALE_AFTER = timedelta(minutes=10)
#: Environments of versions that are no longer served are kept this long, then removed.
ENV_RETENTION = timedelta(days=7)


def _settings(profile: str | None) -> SandboxSettings:
    found = load_config().get(profile or None)
    if found is None:
        raise InvalidConfiguration('sandbox_profile_unknown')
    return found


def _beat(factory: sessionmaker, version_id: UUID) -> None:
    with factory() as db, db.begin():
        db.execute(update(SkillVersionRecord).where(SkillVersionRecord.id == version_id,
                                                    SkillVersionRecord.build_state == 'installing')
                   .values(build_heartbeat_at=utc_now()))


def claim(factory: sessionmaker) -> UUID | None:
    """Take one ``installing`` version nobody is building (no heartbeat yet). Atomic: one worker wins a row."""
    with factory() as db:
        candidates = db.scalars(select(SkillVersionRecord.id).where(
            SkillVersionRecord.build_state == 'installing', SkillVersionRecord.build_heartbeat_at.is_(None))
            .order_by(SkillVersionRecord.created_at).limit(5)).all()
    for candidate in candidates:
        with factory() as db, db.begin():
            won = db.execute(update(SkillVersionRecord).where(
                SkillVersionRecord.id == candidate, SkillVersionRecord.build_state == 'installing',
                SkillVersionRecord.build_heartbeat_at.is_(None)).values(build_heartbeat_at=utc_now())).rowcount
        if won:
            return candidate
    return None


def _fail(factory: sessionmaker, version_id: UUID, error: str, log: str = '') -> None:
    with factory() as db, db.begin():
        row = db.get(SkillVersionRecord, version_id)
        if row is None or row.build_state != 'installing':
            return
        row.build_state, row.build_error, row.build_log = 'failed', error, log[-8000:]
        audit(db, row.tenant_id, row.created_by, 'skill.install_failed', 'skill', str(row.skill_id),
              {'version': row.version, 'error': error})


def _files(db: Session, row: SkillVersionRecord) -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {item.path: item.content for item in db.scalars(select(SkillVersionFileRecord).where(
        SkillVersionFileRecord.version_id == row.id))}
    files['SKILL.md'] = row.skill_md
    return files


def run_build(factory: sessionmaker, version_id: UUID) -> str:
    """Build one claimed version and bring it into service. Returns the resulting state (``ready`` / ``failed`` /
    ``cancelled`` when it was stopped meanwhile). Never raises: a problem becomes ``failed`` with a stable code."""
    staging: Path | None = None
    try:
        with factory() as db:
            row = db.get(SkillVersionRecord, version_id)
            if row is None or row.build_state != 'installing':
                return 'cancelled'
            profile = (row.extra or {}).get('install', {}).get('profile', '')
            files, digest = _files(db, row), row.content_hash
            binary = service._binary_files(db, row, set(files))
        settings = _settings(profile)
        staging = settings.staging_root / f'{version_id}'
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        _beat(factory, version_id)
        result = asyncio.run(build.build_environment(settings, staging, {**files, **binary}, job=version_id.hex[:12]))
        _beat(factory, version_id)
        if not result.ok:
            _fail(factory, version_id, result.error, result.log)
            return 'failed'
        problem = _verify_environment(staging, files)
        if problem:
            _fail(factory, version_id, problem, result.log)
            return 'failed'
        name = build.environment_name(digest, settings)
        if (staging / 'env').is_dir():
            settings.envs_root.mkdir(parents=True, exist_ok=True)
            target = settings.envs_root / name
            if not target.exists():  # another build of the same content and environment already produced it
                (staging / 'env').rename(target)
                (target / 'installed.json').unlink(missing_ok=True)
        with factory() as db, db.begin():
            row = db.get(SkillVersionRecord, version_id)
            if row is None or row.build_state != 'installing':  # stopped while building
                return 'cancelled'
            skill = db.get(SkillRecord, row.skill_id)
            row.env_ref, row.build_log, row.build_error = name, result.log[-8000:], None
            service.activate(db, skill, row, row.created_by)
        return 'ready'
    except Exception:
        logger.exception('Skill install failed')
        _fail(factory, version_id, 'build_internal_error')
        return 'failed'
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def _verify_environment(staging: Path, files: dict) -> str:
    """Packages named in ``requirements.txt`` must be among those the build reported installed."""
    manifest = files.get(build.PYTHON_MANIFEST)
    if manifest is None:
        return ''
    required, _ = parse_requirements(manifest if isinstance(manifest, str) else manifest.decode('utf-8', 'replace'))
    report = staging / 'env' / 'installed.json'
    try:
        installed = {item['name'] for item in json.loads(report.read_text(encoding='utf-8'))}
    except (OSError, ValueError, KeyError, TypeError):
        return 'verify_failed:installed_list_missing'
    missing = missing_distributions(required, installed)
    return f'verify_failed:not_installed:{missing[0]}' if missing else ''


def tick(factory: sessionmaker) -> bool:
    """One unit of worker time: build one waiting version. True when something was done."""
    version_id = claim(factory)
    if version_id is None:
        return False
    run_build(factory, version_id)
    return True


# ---------------------------------------------------------------------------------------------------- admin actions

def _version(db: Session, tenant_id: UUID, name: str, number: int) -> SkillVersionRecord:
    skill = service.library_skill(db, tenant_id, name)
    row = None if skill is None else db.scalar(select(SkillVersionRecord).where(
        SkillVersionRecord.skill_id == skill.id, SkillVersionRecord.version == number))
    if row is None:
        raise NotFound('skill_not_found')
    return row


def status(db: Session, principal, tenant_id: UUID, name: str, number: int) -> dict:
    """Build state and log of one version. Requires active membership."""
    context(db, principal, tenant_id)
    row = _version(db, tenant_id, name, number)
    return {'skill': name, 'version': number, 'build_state': row.build_state, 'build_error': row.build_error,
            'build_log': row.build_log or '', 'env_ref': row.env_ref,
            'heartbeat_at': row.build_heartbeat_at.isoformat() if row.build_heartbeat_at else None}


def reinstall(db: Session, principal, tenant_id: UUID, name: str, number: int, profile: str | None = None) -> dict:
    """Run the build of a failed (or finished) version again from its stored zip; the skill definition does not change.

    Also how a ready version gets an environment for another sandbox profile: pass that profile. The version being
    served keeps serving while a rebuild runs only when it was ready before (its row is not touched until it finishes).
    """
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, service.PUBLISH_PERMISSION)
        row = _version(db, tenant_id, name, number)
        if row.build_state == 'installing':
            raise Conflict('skill_install_in_progress')
        if row.build_state == 'ready' and row.env_ref is not None and profile is None:
            raise Conflict('skill_already_installed')
        if not service.has_manifest(_files(db, row)):
            raise InvalidConfiguration('skill_has_no_dependencies')
        if db.scalar(select(SkillVersionRecord.id).where(SkillVersionRecord.skill_id == row.skill_id,
                                                         SkillVersionRecord.build_state == 'installing').limit(1)):
            raise Conflict('skill_install_in_progress')
        row.extra = {**row.extra, 'install': {'profile': profile or (row.extra or {}).get('install', {}).get('profile', '')}}
        row.build_state, row.build_error, row.build_heartbeat_at = 'installing', None, None
        audit(db, tenant_id, user.id, 'skill.reinstall', 'skill', str(row.skill_id), {'name': name, 'version': number})
        return {'skill': name, 'version': number, 'build_state': 'installing'}


def stop(db: Session, principal, tenant_id: UUID, name: str, number: int) -> dict:
    """Stop an install that is waiting or running: the version becomes ``failed`` (``install_stopped``)."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        require_api_permission(db, tenant_id, user.id, service.PUBLISH_PERMISSION)
        row = _version(db, tenant_id, name, number)
        if row.build_state != 'installing':
            raise Conflict('skill_not_installing')
        row.build_state, row.build_error = 'failed', 'install_stopped'
        audit(db, tenant_id, user.id, 'skill.install_stopped', 'skill', str(row.skill_id), {'name': name, 'version': number})
        return {'skill': name, 'version': number, 'build_state': 'failed'}


# ---------------------------------------------------------------------------------------------------- cleanup

def reap(factory: sessionmaker, *, now=None) -> dict[str, int]:
    """Fail builds that lost their worker, then remove leftovers. Safe to run from any worker, any number of times.

    - ``installing`` rows whose heartbeat is older than :data:`STALE_AFTER` become ``failed`` (``build_interrupted``);
    - staging directories of versions that are no longer installing are removed;
    - environments no ``ready`` version refers to, older than :data:`ENV_RETENTION`, are removed (the ones a ready
      version refers to are never touched).
    """
    now = now or utc_now()
    counts = {'interrupted': 0, 'staging': 0, 'environments': 0}
    with factory() as db:
        stale = db.scalars(select(SkillVersionRecord.id).where(
            SkillVersionRecord.build_state == 'installing', SkillVersionRecord.build_heartbeat_at.is_not(None),
            SkillVersionRecord.build_heartbeat_at < now - STALE_AFTER)).all()
    for version_id in stale:
        _fail(factory, version_id, 'build_interrupted')
        counts['interrupted'] += 1
    with factory() as db:
        installing = {str(v) for v in db.scalars(select(SkillVersionRecord.id).where(
            SkillVersionRecord.build_state == 'installing'))}
        referenced = {r for r in db.scalars(select(SkillVersionRecord.env_ref).where(
            SkillVersionRecord.build_state == 'ready', SkillVersionRecord.env_ref.is_not(None)))}
    try:
        profiles = load_config().profiles.values()
    except Exception:  # an invalid deployment file must not stop the cleanup of everything else
        return counts
    roots = {settings.staging_root for settings in profiles}
    for root in roots:
        for entry in root.iterdir() if root.is_dir() else []:
            if entry.name not in installing:
                shutil.rmtree(entry, ignore_errors=True)
                counts['staging'] += 1
    cutoff = time.time() - ENV_RETENTION.total_seconds()
    for settings in profiles:
        envs = settings.envs_root
        for entry in envs.iterdir() if envs.is_dir() else []:
            if entry.name not in referenced and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                counts['environments'] += 1
    return counts
