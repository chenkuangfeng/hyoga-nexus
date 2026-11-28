"""Current authorization of context source references, independent of cached content.

A Run's manifest inherits history dependencies so a summary/checkpoint cannot wash away source
restrictions. No allow/deny result survives a request. Batch reads avoid per-source ORM lookups.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import timezone
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from nexus_core.platform import utc_now
from nexus_core.runtime import RuntimeFault
from nexus_core.runtime.context import ContextDependency
from nexus_platform.errors import PlatformError
from nexus_platform.persistence.models import (AgentRecord, AgentVersionRecord, MemoryEntryRecord,
    RunRecord, SkillRecord, SkillVersionRecord, UserRecord, MemoryVersionRecord)


def dependencies_from(data: dict | None) -> tuple[ContextDependency, ...]:
    """Decode a supported ledger; malformed non-legacy data fails closed."""
    if data is None:
        return ()
    try:
        if type(data['schema_version']) is not int or data['schema_version'] != 1:
            raise ValueError('version')
        return tuple(ContextDependency(**d) for d in data['dependencies'])
    except (KeyError, TypeError, ValueError):
        raise RuntimeFault('run_authorization_denied') from None


def merge_dependencies(run: RunRecord, dependencies) -> None:
    """Persist new source references before their content can reach a model request."""
    current = dict(run.context_manifest or {'schema_version': 1})
    values = {d for d in dependencies_from(run.context_manifest)}
    values.update(dependencies)
    current['dependencies'] = [asdict(d) for d in sorted(values,
        key=lambda d: (d.kind, d.resource_id, d.version, d.source_run_id or '', d.permission))]
    run.context_manifest = current


def _expand_history(db: Session, viewer: RunRecord, dependencies):
    """Resolve cross-session Run references iteratively; cycles cannot bypass source checks.

    Actual conversation text is not parsed. Immutable resource bindings and the source's own
    ledger supply transitive dependencies. Deleted/migrated-unknown sources fail closed.
    """
    from nexus_platform.authz.resource_batch import ResourceAuthorizationBatch
    pending = {d for d in dependencies if d.kind == 'history'}
    expanded = {d for d in dependencies if d.kind != 'history'}
    visited = set()
    while pending:
        if any(d.version != 'source-v1' for d in pending):
            return None
        ids = {UUID(d.resource_id) for d in pending} - visited
        pending = set()
        if not ids:
            break
        visited.update(ids)
        ids = list(ids)
        sources = []
        for offset in range(0, len(ids), 400):
            sources.extend(db.scalars(select(RunRecord).where(RunRecord.id.in_(ids[offset:offset + 400]),
                RunRecord.tenant_id == viewer.tenant_id, RunRecord.principal_id == viewer.principal_id)))
        if len(sources) != len(ids):
            return None
        refs = []
        for source in sources:
            if source.context_manifest is None and (source.attempt or source.status != 'queued'):
                return None
            for dependency in dependencies_from(source.context_manifest):
                if dependency.kind == 'history':
                    pending.add(dependency)
                else:
                    expanded.add(dependency)
            refs.extend((r['kind'], r['resource_id'], UUID(r['source_tenant_id']), r.get('resource_version_id'))
                        for r in source.config_snapshot.get('resources', []))
        facts = ResourceAuthorizationBatch(db, viewer.tenant_id, refs)
        for kind, name, origin, version in refs:
            resource = facts.authorize(kind, name, origin, version)
            expanded.add(ContextDependency('resource', str(resource.id), resource.version_id))
    return tuple(expanded)


def sources_allowed(db: Session, run: RunRecord, dependencies) -> bool:
    """Validate batch-loaded sources in this tenant/principal scope. Unknown kinds deny."""
    dependencies = tuple(dependencies)
    if not dependencies:
        return True
    from nexus_platform.memory.switches import memory_state
    from nexus_platform.authz.resources import authorize_resource
    from nexus_platform.memory import providers
    try:
        dependencies = _expand_history(db, run, dependencies)
    except (ValueError, TypeError, KeyError, RuntimeFault, PlatformError):
        return False
    if dependencies is None:
        return False
    kinds: dict[str, list] = {}
    for d in dependencies:
        kinds.setdefault(d.kind, []).append(d)
    try:
        memory = kinds.pop('memory', [])
        if memory:
            if not memory_state(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
                                agent_budgets=run.config_snapshot.get('budgets', {})).available:
                return False
            ids = [UUID(d.resource_id) for d in memory]
            entries = {str(e.id): e for e in db.scalars(select(MemoryEntryRecord).where(MemoryEntryRecord.id.in_(ids)))}
            pairs = [(UUID(d.resource_id), int(d.version)) for d in memory]
            versions = set()
            for offset in range(0, len(pairs), 300):
                versions.update(db.execute(select(MemoryVersionRecord.entry_id, MemoryVersionRecord.version).where(
                    tuple_(MemoryVersionRecord.entry_id, MemoryVersionRecord.version).in_(pairs[offset:offset + 300]))))
            for d in memory:
                e = entries.get(d.resource_id)
                if (e is None or (UUID(d.resource_id), int(d.version)) not in versions
                        or e.tenant_id != run.tenant_id or e.owner_user_id != run.principal_id
                        or not e.active or not e.enabled
                        or (e.valid_until and e.valid_until.replace(tzinfo=timezone.utc) <= utc_now())):
                    return False
        skills = kinds.pop('skill', [])
        if skills:
            ids = [UUID(d.version) for d in skills]
            versions = {str(v.id): v for v in db.scalars(select(SkillVersionRecord).where(SkillVersionRecord.id.in_(ids)))}
            rows = {r.id: r for r in db.scalars(select(SkillRecord).where(
                SkillRecord.id.in_([v.skill_id for v in versions.values()])))}
            from nexus_platform.authz.resource_batch import ResourceAuthorizationBatch
            grants = ResourceAuthorizationBatch(db, run.tenant_id,
                [('skill', rows[v.skill_id].name, v.tenant_id, str(v.id))
                 for v in versions.values() if v.skill_id in rows])
            for d in skills:
                v = versions.get(d.version)
                skill = rows.get(v.skill_id) if v else None
                if (v is None or not v.model_invocable or skill is None or skill.archived_at
                        or str(skill.id) != d.resource_id):
                    return False
                if skill.owner_user_id:
                    if skill.tenant_id != run.tenant_id or skill.owner_user_id != run.principal_id:
                        return False
                else:
                    grants.authorize('skill', skill.name, v.tenant_id, str(v.id))
        resources = kinds.pop('resource', [])
        if resources:
            from nexus_platform.persistence.models import PlatformResourceRecord
            from nexus_platform.authz.resource_batch import ResourceAuthorizationBatch
            rows = {str(r.id): r for r in db.scalars(select(PlatformResourceRecord).where(
                PlatformResourceRecord.id.in_([UUID(d.resource_id) for d in resources])))}
            grants = ResourceAuthorizationBatch(db, run.tenant_id,
                [(r.kind, r.resource_id, r.tenant_id, r.version_id) for r in rows.values()])
            for d in resources:
                row = rows.get(d.resource_id)
                if row is None or not row.active or row.version_id != d.version:
                    return False
                grants.authorize(row.kind, row.resource_id, row.tenant_id, row.version_id, d.permission)
        knowledge = kinds.pop('knowledge', [])
        if knowledge:
            from nexus_platform.knowledge.access import readable_bases
            readable = {str(b.id) for b in readable_bases(db, run.tenant_id, run.principal_id,
                                                         [UUID(d.resource_id) for d in knowledge])}
            if any(d.resource_id not in readable for d in knowledge):
                return False
        external = kinds.pop('provider', [])
        if external:
            if not memory_state(db, tenant_id=run.tenant_id, owner_id=run.principal_id).available:
                return False
            provider = providers.selected_provider(db, run.tenant_id)
            if provider is None or any(d.resource_id != provider.name or
                    d.version != providers.generation(provider.name) for d in external):
                return False
        mcp = kinds.pop('mcp', [])
        if mcp:
            from nexus_platform.mcp.service import visible_tools, context_version
            current = {(str(t.service_id), context_version(t)) for t in visible_tools(
                db, run.tenant_id, {UUID(d.resource_id) for d in mcp})}
            if any((d.resource_id, d.version) not in current for d in mcp):
                return False
        # Plugin registration is checked by the application-owned registry before model entry.
        # The durable token includes a process-instance generation; a resumed worker must re-register
        # and explicitly validate it, rather than treating persisted plugin text as trusted.
        plugins = kinds.pop('plugin', [])
        if plugins:
            from nexus_platform.runs.context_plugins import plugin_dependencies_allowed
            if not plugin_dependencies_allowed(plugins):
                return False
        return not kinds
    except (ValueError, TypeError, PlatformError):
        return False


def require_context_access(db: Session, run: RunRecord, history_ids=()) -> None:
    """One attempt gate for identity, Agent, model, history grants and injected sources."""
    from nexus_platform.identity.service import require_membership, require_tenant
    from nexus_platform.agents.access import require_agent_permission
    from nexus_platform.models.provider_settings import authorize_model
    from .messages import histories_allowed
    try:
        require_tenant(db, run.tenant_id)
        require_membership(db, run.tenant_id, run.principal_id)
        user = db.get(UserRecord, run.principal_id)
        version = db.get(AgentVersionRecord, UUID(run.config_snapshot['agent_version_id']))
        agent = db.get(AgentRecord, version.agent_id) if version else None
        if user is None or user.status != 'active' or agent is None or agent.status == 'archived':
            raise RuntimeFault('run_authorization_denied')
        require_agent_permission(db, run.tenant_id, run.principal_id, agent, 'run')
        authorize_model(db, run.tenant_id, run.principal_id, UUID(run.config_snapshot['model_profile_version_id']))
        ids = set(history_ids) | {run.id}
        sources = []
        ordered = list(ids)
        for offset in range(0, len(ordered), 400):
            sources.extend(db.scalars(select(RunRecord).where(RunRecord.id.in_(ordered[offset:offset + 400]))))
        if len(sources) != len(ids) or not all(histories_allowed(db, sources, viewer=run).values()):
            raise RuntimeFault('run_authorization_denied')
    except (ValueError, TypeError, PlatformError):
        raise RuntimeFault('run_authorization_denied') from None
