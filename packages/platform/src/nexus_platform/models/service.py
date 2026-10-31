from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import (
    CredentialReferenceRecord,
    ModelProfileRecord,
    ModelProfileVersionRecord,
    ModelProviderRecord, ProviderModelRecord, ProviderCredentialRecord,
)
from nexus_platform.tenants.service import ADMIN_ROLES
from nexus_platform.authz.audit import audit


def create_model_profile(
    session: Session,
    principal: Principal,
    tenant_id: UUID,
    *,
    name: str,
    provider: str,
    model_name: str,
    options: dict[str, Any],
    credential_reference_id: UUID | None = None,
) -> tuple[ModelProfileRecord, ModelProfileVersionRecord]:
    now = utc_now()
    options = clean_public_options(options)
    name, provider, model_name = name.strip(), provider.strip(), model_name.strip()
    if not name or not provider or not model_name:
        raise ValueError("Model profile name, provider, and model name must not be empty")
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id, roles=ADMIN_ROLES)
        if credential_reference_id is not None:
            if session.scalar(select(ProviderCredentialRecord.credential_id).where(ProviderCredentialRecord.credential_id == credential_reference_id)):
                raise ValueError('Manage stored credentials through model settings')
            reference = session.get(CredentialReferenceRecord, credential_reference_id)
            if reference is None or reference.tenant_id != tenant_id or reference.status != "active":
                raise NotFound("Credential reference not found")
        profile = ModelProfileRecord(
            id=new_id(),
            tenant_id=tenant_id,
            name=name.strip(),
            provider=provider.strip(),
            current_version_id=None,
            created_by=user.id,
            created_at=now,
        )
        session.add(profile)
        session.flush()
        version = ModelProfileVersionRecord(
            id=new_id(),
            profile_id=profile.id,
            tenant_id=tenant_id,
            version=1,
            model_name=model_name.strip(),
            options=options,
            credential_reference_id=credential_reference_id,
            content_hash=content_hash(
                {"provider": profile.provider, "model_name": model_name.strip(), "options": options,
                "credential_reference_id": str(credential_reference_id) if credential_reference_id else None}
            ),
            created_at=now,
        )
        session.add(version)
        session.flush()
        profile.current_version_id = version.id
        audit(session, tenant_id, user.id, "model_profile.created", "model_profile", str(profile.id))
    return profile, version


def update_model_profile(
    session: Session,
    principal: Principal,
    tenant_id: UUID,
    profile_id: UUID,
    *,
    model_name: str,
    options: dict[str, Any],
    credential_reference_id: UUID | None,
) -> ModelProfileVersionRecord:
    now = utc_now()
    options = clean_public_options(options)
    model_name = model_name.strip()
    if not model_name:
        raise ValueError("Model name must not be empty")
    with session.begin():
        user = resolve_user(session, principal)
        require_tenant(session, tenant_id)
        require_membership(session, tenant_id, user.id, roles=ADMIN_ROLES)
        profile = session.scalar(
            select(ModelProfileRecord).where(
                ModelProfileRecord.id == profile_id, ModelProfileRecord.tenant_id == tenant_id
            ).with_for_update()
        )
        if session.get(ProviderModelRecord, profile_id):
            raise ValueError('Manage this model through model settings')
        if profile is None:
            raise NotFound("Model profile not found")
        if credential_reference_id is not None:
            if session.scalar(select(ProviderCredentialRecord.credential_id).where(ProviderCredentialRecord.credential_id == credential_reference_id)):
                raise ValueError('Manage stored credentials through model settings')
            reference = session.get(CredentialReferenceRecord, credential_reference_id)
            if reference is None or reference.tenant_id != tenant_id or reference.status != "active":
                raise NotFound("Credential reference not found")
        version_number = session.scalar(
            select(func.coalesce(func.max(ModelProfileVersionRecord.version), 0)).where(
                ModelProfileVersionRecord.profile_id == profile.id
            )
        ) + 1
        version = ModelProfileVersionRecord(
            id=new_id(), profile_id=profile.id, tenant_id=tenant_id,
            version=version_number, model_name=model_name.strip(),
            options=options, credential_reference_id=credential_reference_id,
            content_hash=content_hash({"provider": profile.provider, "model_name": model_name.strip(),
                                       "options": options,
                                       "credential_reference_id": str(credential_reference_id) if credential_reference_id else None}),
            created_at=now,
        )
        session.add(version)
        session.flush()
        profile.current_version_id = version.id
        audit(session, tenant_id, user.id, "model_profile.version_created", "model_profile", str(profile.id),
              {"version": version_number})
    return version


def get_model_profile(session: Session, tenant_id: UUID, profile_id: UUID):
    profile = session.scalar(
        select(ModelProfileRecord).where(
            ModelProfileRecord.tenant_id == tenant_id, ModelProfileRecord.id == profile_id
        )
    )
    if profile is None:
        raise NotFound("Model profile not found")
    version = session.get(ModelProfileVersionRecord, profile.current_version_id) if profile.current_version_id else None
    return profile, version


def clean_public_options(value: Any, path: str = "options") -> Any:
    forbidden_exact = {
        "api_key", "apikey", "token", "access_token", "refresh_token", "password", "secret",
        "client_secret", "authorization", "credential_value",
    }
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in forbidden_exact or normalized.endswith(
                ("_api_key", "_apikey", "_token", "_password", "_secret", "_authorization")
            ):
                raise ValueError(f"Sensitive option is not allowed at {path}.{key}; use a CredentialRef")
            clean[str(key)] = clean_public_options(item, f"{path}.{key}")
        return clean
    if isinstance(value, list):
        return [clean_public_options(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, str):
        if re.search(
            r"(?i)(?:sk-[a-z0-9]{20,}|bearer\s+\S+|(?:api[_-]?key|password|token|client[_-]?secret)\s*[:=]\s*\S+)",
            value,
        ):
            raise ValueError(f"Possible credential value is not allowed at {path}; use a CredentialRef")
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    raise ValueError(f"Unsupported configuration value at {path}")


def content_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
