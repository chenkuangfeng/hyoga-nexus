"""Durable execution messages; model execution stays in runtimes."""
from __future__ import annotations
from dataclasses import asdict
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from nexus_core.platform import new_id, utc_now
from nexus_core.runtime import ModelMessage
from nexus_platform.errors import PlatformError
from nexus_platform.persistence.models import MessageRecord, RunRecord, SessionRecord
from nexus_platform.authz.resources import authorize_resource
from .domain import Run


from nexus_platform.sessions.snapshot import advance


def add_message(db: Session, run: RunRecord | Run, message: ModelMessage, *, origin: str = "runtime") -> MessageRecord:
    session_row = db.scalar(select(SessionRecord).where(SessionRecord.id == run.session_id).with_for_update())
    session_row.updated_at = utc_now()
    advance(db, run.session_id)
    sequence = db.scalar(select(func.coalesce(func.max(MessageRecord.sequence), 0)).where(
        MessageRecord.session_id == run.session_id)) + 1
    row = MessageRecord(id=new_id(), session_id=run.session_id, run_id=run.id, sequence=sequence,
        role=message.role, content=message.content, created_at=utc_now(),
        runtime_metadata={'origin': origin, 'context_source': message.context_source, 'tool_calls': [asdict(call) for call in message.tool_calls],
                          'tool_call_id': message.tool_call_id})
    db.add(row)
    if message.context_source:
        from nexus_core.runtime.context import context_digest
        source_run = db.get(RunRecord, run.id)
        manifest = dict(source_run.context_manifest or {'schema_version': 1, 'dependencies': []})
        blocks = dict(manifest.get('block_digests', []))
        blocks[message.context_source] = context_digest(message.content)
        manifest['block_digests'] = sorted(blocks.items())
        source_run.context_manifest = manifest
    return row


def _grant_allowed(db: Session, key: tuple) -> bool:
    """One resource grant check; a failed check is a denial, not an error."""
    tenant_id, kind, resource_id, source_tenant_id, version_id = key
    try:
        authorize_resource(db, tenant_id, kind, resource_id, source_tenant_id=UUID(source_tenant_id),
                           resource_version_id=version_id, permission='use')
        return True
    except PlatformError:
        return False


def histories_allowed(db: Session, runs, *, viewer: RunRecord | None = None) -> dict[UUID, bool]:
    """Decide history visibility for many Runs with one check per distinct resource grant (P8).

    A Run's history is visible only if every resource in its snapshot is still granted. Grants are
    read from the database on every call, so revocation takes effect on the next preparation; only
    the repeated checks for the same grant within one call are merged.
    """
    from .context_access import dependencies_from, sources_allowed
    from nexus_platform.authz.resource_batch import ResourceAuthorizationBatch
    runs = list(runs)
    grouped = {}
    for source in runs:
        grouped.setdefault(source.tenant_id, []).extend((r['kind'], r['resource_id'], UUID(r['source_tenant_id']),
            r.get('resource_version_id')) for r in source.config_snapshot.get('resources', []))
    batches = {tenant: ResourceAuthorizationBatch(db, tenant, refs) if len(set(refs)) > 4 else None
               for tenant, refs in grouped.items()}
    # One source-fact read for each principal/memory-policy scope, even when many earlier
    # Runs inherit the same dependencies. Only the rare mixed-denial case needs finer checks.
    from nexus_memory.switches import agent_preference
    def scope_key(source):
        owner = viewer if viewer is not None else source
        return (owner.tenant_id, owner.principal_id, agent_preference(owner.config_snapshot.get('budgets')))
    scopes = {}
    invalid_sources = set()
    dependencies_by_run = {}
    from nexus_core.runtime import RuntimeFault
    for source in runs:
        try:
            dependencies_by_run[source.id] = dependencies_from(source.context_manifest)
        except RuntimeFault:
            # Legacy/malformed ledgers are invisible, not a reason to reveal their raw text
            # or to discard unrelated valid historical turns.
            dependencies_by_run[source.id] = ()
            invalid_sources.add(source.id)
    for source in runs:
        scope = scope_key(source)
        scopes.setdefault(scope, []).append(source)
    source_decisions = {}
    for scope, sources in scopes.items():
        dependencies = {d for source in sources for d in dependencies_by_run[source.id]}
        owner = viewer if viewer is not None else sources[0]
        if sources_allowed(db, owner, dependencies):
            source_decisions[scope] = {d: True for d in dependencies}
        else:
            source_decisions[scope] = {d: sources_allowed(db, owner, (d,)) for d in dependencies}
    decisions: dict[tuple, bool] = {}
    results: dict[UUID, bool] = {}
    for run in runs:
        allowed = True
        for resource in run.config_snapshot.get('resources', []):
            key = (run.tenant_id, resource['kind'], resource['resource_id'], resource['source_tenant_id'],
                   resource.get('resource_version_id'))
            if key not in decisions:
                try:
                    batch = batches[run.tenant_id]
                    if batch is None:
                        decisions[key] = _grant_allowed(db, key)
                    else:
                        batch.authorize(resource['kind'], resource['resource_id'],
                            UUID(resource['source_tenant_id']), resource.get('resource_version_id'))
                        decisions[key] = True
                except PlatformError:
                    decisions[key] = False
            if not decisions[key]:
                allowed = False
                break
        scope = scope_key(run)
        results[run.id] = (allowed and run.id not in invalid_sources
                           and all(source_decisions[scope][d] for d in dependencies_by_run[run.id]))
    return results


def _history_allowed(db: Session, run: RunRecord) -> bool:
    return histories_allowed(db, [run])[run.id]
