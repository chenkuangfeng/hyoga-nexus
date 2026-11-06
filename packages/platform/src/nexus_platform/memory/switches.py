"""Platform facade for the long-term memory switches (openspec 2026-11-05-memory-switches).

Reads and writes the space settings (`memory_space_settings`) and the member's own switch
(`memory_capture_settings.memory_enabled`), and computes the effective state with
`nexus_memory.switches.resolve`. Use points:

- Run preparation: skip the memory index and remove memory tools when memory is off.
- Tool gateway (`runs/store.py` `authorize`): refuse memory tool calls with `memory_disabled`.
- Capture: do not queue jobs, and skip queued ones, when memory is off or the space is `explicit`.

`memory_state` runs inside the caller's transaction and never commits. The HTTP helpers open their own
transaction, resolve the caller, and write an audit record for every change.
"""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from nexus_core.platform import Principal, utc_now
from nexus_memory import switches as rules
from nexus_memory import text as memtext
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Forbidden
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import MemoryCaptureSettingsRecord, MemorySpaceSettingsRecord
from nexus_platform.tenants.service import ADMIN_ROLES


def memory_state(db: Session, *, tenant_id: UUID, owner_id: UUID,
                 agent_budgets: Mapping[str, Any] | None = None) -> rules.MemoryState:
    """Effective memory state for one owner; pass the agent version's budgets when a Run is involved."""
    space = db.get(MemorySpaceSettingsRecord, tenant_id)
    member = db.get(MemoryCaptureSettingsRecord, (tenant_id, owner_id))
    return rules.resolve(
        space_enabled=space.enabled if space else rules.DEFAULT_SPACE_ENABLED,
        write_mode=space.write_mode if space else rules.DEFAULT_WRITE_MODE,
        user_enabled=member.memory_enabled if member else True,
        agent_enabled=rules.agent_preference(agent_budgets),
    )


# ---------------------------------------------------------------- space settings

def space_settings(db: Session, principal: Principal, tenant_id: UUID) -> dict[str, Any]:
    """The space's memory settings for any member; `can_edit` tells the page whether to allow changes."""
    with db.begin():
        _, membership = context(db, principal, tenant_id)
        row = db.get(MemorySpaceSettingsRecord, tenant_id)
        return _space_view(row, can_edit=membership.role in ADMIN_ROLES)


#: Longest custom extraction rules a space may set (openspec 2026-11-06-memory-evolution B6).
EXTRACT_INSTRUCTIONS_LIMIT = 1000


def set_space_settings(db: Session, principal: Principal, tenant_id: UUID, *, enabled: bool,
                       write_mode: str, extract_instructions: str | None = None) -> dict[str, Any]:
    """Change the space switch, write mode and, when given, the custom extraction rules.

    Only owners and admins; non-members get 404 from `context`. The rules are added to every extraction
    prompt as fenced data, so they are screened like memory content: a threat pattern is refused (422).
    `None` keeps the current rules; an empty string clears them.
    """
    if write_mode not in rules.WRITE_MODES:
        raise ValueError('Memory write mode is invalid')
    if extract_instructions is not None:
        extract_instructions = extract_instructions.strip()
        if len(extract_instructions) > EXTRACT_INSTRUCTIONS_LIMIT:
            raise ValueError('Extraction rules are too long')
        if memtext.screen(extract_instructions).threats:
            raise ValueError('Extraction rules contain disallowed instructions')
    with db.begin():
        user, membership = context(db, principal, tenant_id)
        if membership.role not in ADMIN_ROLES:
            raise Forbidden('Only space owners and admins can change memory settings')
        row = db.get(MemorySpaceSettingsRecord, tenant_id, with_for_update=True)
        if row is None:
            row = MemorySpaceSettingsRecord(tenant_id=tenant_id)
            db.add(row)
        row.enabled, row.write_mode = enabled, write_mode
        if extract_instructions is not None:
            row.extract_instructions = extract_instructions
        row.updated_by, row.updated_at = user.id, utc_now()
        audit(db, tenant_id, user.id, 'memory.space_settings', 'tenant', str(tenant_id),
              {'enabled': enabled, 'write_mode': write_mode,
               'extract_instructions_chars': len(row.extract_instructions or '')})
        return _space_view(row, can_edit=True)


def _space_view(row: MemorySpaceSettingsRecord | None, *, can_edit: bool) -> dict[str, Any]:
    if row is None:
        return {'enabled': rules.DEFAULT_SPACE_ENABLED, 'write_mode': rules.DEFAULT_WRITE_MODE,
                'extract_instructions': '', 'can_edit': can_edit, 'updated_at': None}
    return {'enabled': row.enabled, 'write_mode': row.write_mode, 'extract_instructions': row.extract_instructions or '',
            'can_edit': can_edit, 'updated_at': row.updated_at.isoformat() if row.updated_at else None}


def extract_instructions(db: Session, tenant_id: UUID) -> str:
    """The space's custom extraction rules, '' when none; caller transaction."""
    row = db.get(MemorySpaceSettingsRecord, tenant_id)
    return (row.extract_instructions or '') if row else ''


# ---------------------------------------------------------------- member preference

def preferences(db: Session, principal: Principal, tenant_id: UUID) -> dict[str, Any]:
    """The caller's own switch plus the effective state without an agent (the page has no agent context)."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        return _preference_view(db, tenant_id, user.id)


def set_preferences(db: Session, principal: Principal, tenant_id: UUID, *, memory_enabled: bool) -> dict[str, Any]:
    """Turn the caller's own memory on or off in this space; automatic capture settings are kept."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        row = db.get(MemoryCaptureSettingsRecord, (tenant_id, user.id), with_for_update=True)
        if row is None:
            row = MemoryCaptureSettingsRecord(tenant_id=tenant_id, owner_user_id=user.id, enabled=False,
                                              capacity_policy='reject')
            db.add(row)
        row.memory_enabled = memory_enabled
        row.updated_at = utc_now()
        db.flush()
        audit(db, tenant_id, user.id, 'memory.preferences', 'memory_capture', str(user.id),
              {'memory_enabled': memory_enabled})
        return _preference_view(db, tenant_id, user.id)


def _preference_view(db: Session, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    member = db.get(MemoryCaptureSettingsRecord, (tenant_id, user_id))
    state = memory_state(db, tenant_id=tenant_id, owner_id=user_id)
    return {'memory_enabled': member.memory_enabled if member else True, 'effective': state.available,
            'reason': state.reason, 'write_mode': state.write_mode}
