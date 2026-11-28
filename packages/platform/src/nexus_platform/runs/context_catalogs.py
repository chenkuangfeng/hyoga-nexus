"""Authorized context contributors backed by the platform's existing domain services.

Providers read only within the caller's short transaction and return plain immutable values.
External memory hooks are collected separately, outside this transaction. Rendering v1 preserves
existing prompt bytes; these objects do not register tools or make authorization decisions reusable.
"""
from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy.orm import Session
from nexus_platform.persistence.models import AgentVersionRecord, RunRecord

from nexus_core.platform import utc_now
from nexus_core.runtime.context import ContextBlock, ContextDependency


@dataclass(frozen=True)
class MemoryContribution:
    """Local memory content and usage metadata copied out of the database transaction."""
    blocks: tuple[ContextBlock, ...]
    enabled: bool
    resident_entries: tuple[dict, ...] = ()
    recall_entries: tuple[dict, ...] = ()
    provider_name: str | None = None
    provider_generation: str = ''
    need_snapshot: bool = False


class MemoryContextProvider:
    """Freeze a session index and recall from the original user query under all memory switches."""

    def build(self, db: Session, run: RunRecord, version: AgentVersionRecord, query: str) -> MemoryContribution:
        from nexus_memory import service as rules
        from nexus_memory.switches import profile_injection_enabled, recall_enabled
        from nexus_platform.memory.snapshots import session_snapshot
        from nexus_platform.memory.switches import memory_state
        from nexus_platform.memory.repository import SqlMemoryRepository
        from nexus_platform.memory import providers
        if not memory_state(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
                            agent_budgets=version.budgets).available:
            return MemoryContribution((), False)
        profile_enabled = profile_injection_enabled(version.budgets)
        snapshot = session_snapshot(db, tenant_id=run.tenant_id, owner_id=run.principal_id,
            session_id=run.session_id, project=version.budgets.get('behavior', {}).get('project_name', ''),
            include_profile=False)
        import re
        index_text = re.sub(r'<user_memory kind="profile">[\s\S]*?</user_memory>\n?', '', snapshot.index_text)
        resident_ids = {str(item['id']) for item in (snapshot.resident_entries or [])}
        dependencies = tuple(ContextDependency(**d) for d in (snapshot.context_dependencies or [])
                             if not (d.get('kind') == 'memory' and d.get('resource_id') in resident_ids))
        blocks = []
        if index_text:
            blocks.append(ContextBlock('memory:index', 'memory', 'system', 'system_catalog', 10,
                '\nPublished memory/SOP index (read authorized entries on demand):\n' + index_text,
                lifetime='session', dependencies=dependencies))
        resident_entries = ()
        if profile_enabled:
            profile_snapshot = rules.snapshot(SqlMemoryRepository(db), run.tenant_id, run.principal_id,
                version.budgets.get('behavior', {}).get('project_name', ''), now=utc_now(), include_profile=True)
            match = re.search(r'<user_memory kind="profile">[\s\S]*?</user_memory>', profile_snapshot.text)
            resident_entries = tuple(profile_snapshot.resident)
            if match:
                profile_ids = {item['id'] for item in resident_entries}
                profile_dependencies = tuple(ContextDependency(**d) for d in profile_snapshot.dependencies
                                             if d.get('resource_id') in profile_ids)
                blocks.append(ContextBlock('memory:profile', 'memory', 'system', 'system_catalog', 35,
                    match.group(0), dependencies=profile_dependencies))
        recall_entries = ()
        if query and recall_enabled(version.budgets):
            resident = frozenset(item['id'] for item in resident_entries)
            recall = rules.recall(SqlMemoryRepository(db), run.tenant_id, run.principal_id,
                                  query, exclude=resident, now=utc_now())
            if recall.text:
                recall_entries = recall.entries
                blocks.append(ContextBlock('memory:recall', 'memory', 'user', 'history_prefix', 10,
                    recall.text, dependencies=tuple(ContextDependency('memory', item['id'], str(item['version']))
                                                    for item in recall.entries)))
        provider = providers.provider_for(db, run.tenant_id)
        return MemoryContribution(tuple(blocks), True, resident_entries,
            recall_entries, provider.name if provider else None, providers.generation(provider.name) if provider else '',
            bool(provider and not any(d.kind == 'provider' for d in dependencies)))


class SkillCatalogProvider:
    """Bounded frozen metadata; skill bodies and resource files remain lazily authorized tools."""

    def build(self, db: Session, run: RunRecord, version: AgentVersionRecord) -> tuple[ContextBlock, ...]:
        from sqlalchemy import select
        from nexus_platform.persistence.models import ResourceBindingRecord, SessionSkillSnapshotRecord
        from nexus_platform.skills.service import session_index
        if not db.scalar(select(ResourceBindingRecord.id).where(
                ResourceBindingRecord.agent_version_id == version.id,
                ((ResourceBindingRecord.kind == 'skill') | ((ResourceBindingRecord.kind == 'tool') &
                    (ResourceBindingRecord.resource_id == 'load_skill')))).limit(1)):
            return ()
        text = session_index(db, run.tenant_id, run.session_id, version.id, run.principal_id)
        if not text:
            return ()
        snapshot = db.get(SessionSkillSnapshotRecord, run.session_id)
        return (ContextBlock('skills:catalog', 'skills', 'system', 'system_catalog', 20,
            '\nSkills (load a skill with load_skill; resource files with read_skill_file; '
            'skills grant no permissions):\n' + text, lifetime='session',
            dependencies=tuple(ContextDependency(**d) for d in snapshot.context_dependencies or [])),)


class KnowledgeCatalogProvider:
    """Names only currently readable bound bases and records their per-user visibility dependencies."""

    def build(self, db: Session, run: RunRecord, version: AgentVersionRecord) -> tuple[bool, tuple[ContextBlock, ...]]:
        from nexus_platform.knowledge.tools import bound_base_ids
        from nexus_platform.knowledge import access
        bound = bound_base_ids(db, version.id)
        if not bound:
            return False, ()
        bases = access.readable_bases(db, run.tenant_id, run.principal_id, bound)
        lines = []
        for base in sorted(bases, key=lambda base: str(base.id)):
            profile = ((base.settings or {}).get('generated_profile') or {}).get('description', '')
            description = ' '.join((base.description or profile or '').split())[:240]
            lines.append(f'- {base.name} (id {base.id})' + (f': {description}' if description else ''))
        if not lines:
            return True, ()
        return True, (ContextBlock('knowledge:catalog', 'knowledge', 'system', 'system_catalog', 30,
            '\nKnowledge bases (search with search_knowledge; end each sentence that uses a '
            'passage with its [ID:n]):\n' + '\n'.join(lines),
            dependencies=tuple(ContextDependency('knowledge', str(b.id), 'catalog-v1') for b in sorted(bases, key=lambda base: str(base.id)))),)
