"""User preferences (`users.preferences`). Only known keys are accepted.

- `last_active_tenant_id`: the space to open at sign-in. It is honoured only while the user is still an
  active member of that space; an empty value clears it.
- `browser_search_instructions`, `gallery`: UI preferences stored as given (the server does not interpret them).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from nexus_core.platform import Principal
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.orgs.access import membership_is_active
from nexus_platform.persistence.models import MembershipRecord

KNOWN_KEYS = frozenset({"last_active_tenant_id", "browser_search_instructions", "gallery"})
OPAQUE_KEYS = frozenset({"browser_search_instructions", "gallery"})


def get_preferences(session: Session, principal: Principal) -> dict[str, Any]:
    with session.begin():
        user = resolve_user(session, principal)
        return dict(user.preferences or {})


def update_preferences(session: Session, principal: Principal, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge `patch` into the user's preferences. Unknown keys are refused with ValueError."""
    unknown = set(patch) - KNOWN_KEYS
    if unknown:
        raise ValueError(f"Unknown preference: {', '.join(sorted(unknown))}")
    with session.begin():
        user = resolve_user(session, principal)
        current = dict(user.preferences or {})
        if "last_active_tenant_id" in patch:
            value = patch["last_active_tenant_id"]
            if value in (None, ""):
                current.pop("last_active_tenant_id", None)
            else:
                try:
                    tenant_id = UUID(str(value))
                except ValueError as exc:
                    raise ValueError("last_active_tenant_id must be a space id") from exc
                membership = session.get(MembershipRecord, (tenant_id, user.id))
                if not membership_is_active(session, membership):  # also covers a missing membership
                    raise NotFound("Tenant not found")
                current["last_active_tenant_id"] = str(tenant_id)
        for key in OPAQUE_KEYS & set(patch):
            if patch[key] is None:
                current.pop(key, None)
            else:
                current[key] = patch[key]
        user.preferences = current
        return current

