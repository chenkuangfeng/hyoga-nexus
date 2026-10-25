"""Scoped model settings and write-only, authenticated credential storage."""
from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from nexus_core.platform import Principal, CredentialRef

from nexus_core.platform import new_id, utc_now
from nexus_platform.errors import Forbidden, NotFound, ServiceUnavailable, Conflict
from nexus_platform.identity.service import resolve_user, require_workspace, require_membership
from nexus_platform.models.service import content_hash
from nexus_platform.models.ports import CredentialLease, CredentialResolver
from nexus_platform.persistence.models import (
    ModelProviderRecord as Provider, ProviderModelRecord as Link, ModelDefaultRecord as Default,
    CredentialReferenceRecord as Credential, ModelProfileRecord as Profile,
    ModelProfileVersionRecord as Version, RunRecord, ProviderCredentialRecord as StoredKey,
    UserRecord, MembershipRecord,
)
from nexus_platform.workspaces.service import ADMIN_ROLES, audit


def cipher() -> Fernet:
    """Load the deployment Fernet key; raise ServiceUnavailable rather than generate a fallback.

    API and worker must share this key. Its value never leaves the credential adapter."""
    try:
        return Fernet(os.environ['NEXUS_CREDENTIAL_ENCRYPTION_KEY'].encode('ascii'))
    except (KeyError, ValueError, UnicodeError):
        raise ServiceUnavailable('Credential encryption key is not configured correctly') from None


def encrypt(value: str, credential_id: UUID) -> str:
    """Encrypt a secret bound to its credential ID; return an opaque database-safe token.

    Authentication covers both the reference and secret, so swapping encrypted rows fails closed."""
    # Bind authenticated plaintext to its opaque reference to prevent ciphertext swapping.
    return cipher().encrypt((str(credential_id) + '\n' + value).encode()).decode()


def decrypt(provider: StoredKey) -> str:
    """Resolve one authenticated stored secret in memory.

    The caller must first authorize the provider and reference. Invalid tokens or a different
    deployment key raise ServiceUnavailable without including ciphertext or secret values."""
    try:
        text = cipher().decrypt(provider.encrypted_key.encode()).decode()
        identity, secret = text.split('\n', 1)
        if identity != str(provider.credential_id):
            raise InvalidToken
        return secret
    except (InvalidToken, ValueError, UnicodeError):
        raise ServiceUnavailable('Stored credential cannot be decrypted') from None


def context(db: Session, principal: Principal, workspace_id: UUID) -> tuple[UserRecord, MembershipRecord]:
    """Resolve the authenticated user and active Workspace membership in the caller transaction."""
    user = resolve_user(db, principal)
    require_workspace(db, workspace_id)
    membership = require_membership(db, workspace_id, user.id)
    return user, membership


def provider_access(db: Session, workspace_id: UUID, user_id: UUID, provider_id: UUID, *, manage: bool = False) -> Provider:
    """Require an active provider in this Workspace and the caller’s personal scope.

    Reads hide private/disabled resources as NotFound. Management of shared providers
    additionally requires an administrator and locks the row for consistent updates."""
    row = db.scalar(select(Provider).where(Provider.id == provider_id).with_for_update()) if manage else db.get(Provider, provider_id)
    if not row or row.workspace_id != workspace_id or not row.active:
        raise NotFound('Provider unavailable')
    if row.owner_user_id is not None and row.owner_user_id != user_id:
        raise NotFound('Provider unavailable')
    if manage and row.owner_user_id is None:
        require_membership(db, workspace_id, user_id, roles=ADMIN_ROLES)
    return row


def authorize_model(db: Session, workspace_id: UUID, user_id: UUID, version_id: UUID) -> Version:
    """Check version, current credential, provider ownership and model availability.

    Historical versions remain valid until explicitly disabled. This check is shared by
    publication, Session/Run creation and execution so an Agent cannot grant personal Key access."""
    version = db.get(Version, version_id)
    if not version or version.workspace_id != workspace_id:
        raise NotFound('Model unavailable')
    if version.credential_reference_id:
        ref = db.get(Credential, version.credential_reference_id)
        if not ref or ref.workspace_id != workspace_id or ref.status != 'active':
            raise NotFound('Model credential unavailable')
        secret = db.get(StoredKey, version.credential_reference_id)
        if secret:
            provider_access(db, workspace_id, user_id, secret.provider_id)
    link = db.get(Link, version.profile_id)
    if link:
        if not link.active:
            raise NotFound('Model unavailable')
        provider_access(db, workspace_id, user_id, link.provider_id)
    return version


def view(db: Session, row: Provider) -> dict[str, object]:
    """Project public provider metadata and active current model versions; never expose a Key."""
    models = []
    for link in db.scalars(select(Link).where(Link.provider_id == row.id, Link.active.is_(True))):
        profile = db.get(Profile, link.profile_id)
        version = db.get(Version, profile.current_version_id)
        models.append({'id': str(profile.id), 'name': version.model_name,
                       'version_id': str(version.id), 'version': version.version})
    return {'id': str(row.id), 'name': row.name, 'base_url': row.base_url,
            'scope': 'personal' if row.owner_user_id else 'workspace',
            'key_configured': True, 'key_mask': '••••••••', 'models': models}


def list_settings(db: Session, principal: Principal, workspace_id: UUID) -> dict[str, object]:
    """Return only visible providers, authorized defaults and the caller’s management capability.

    Unavailable defaults are omitted; no private configuration is returned to space administrators."""
    with db.begin():
        user, membership = context(db, principal, workspace_id)
        rows = db.scalars(select(Provider).where(Provider.workspace_id == workspace_id, Provider.active.is_(True)))
        providers = [view(db, row) for row in rows if row.owner_user_id in (None, user.id)]
        defaults = {}
        for scope, key in [('personal', str(user.id)), ('workspace', 'workspace')]:
            item = db.get(Default, (workspace_id, key))
            if item:
                try:
                    authorize_model(db, workspace_id, user.id, item.version_id)
                    defaults[scope] = str(item.version_id)
                except (NotFound, Forbidden):
                    pass
        return {'providers': providers, 'defaults': defaults, 'can_manage_workspace': membership.role in ADMIN_ROLES}


def save_provider(db: Session, principal: Principal, workspace_id: UUID, *, name: str, base_url: str, scope: str, api_key: str | None, provider_id: UUID | None = None) -> dict[str, object]:
    """Create or update an authorized provider in one transaction and return public metadata.

    Address changes require a replacement Key and new references, preserving historical
    destinations. Same-address replacement rotates credentials for subsequent resolutions.
    Missing encryption configuration fails without persisting plaintext."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        if provider_id:
            row = provider_access(db, workspace_id, user.id, provider_id, manage=True)
            if scope != ('personal' if row.owner_user_id else 'workspace'):
                raise Conflict('Provider scope cannot be changed')
        else:
            if scope == 'workspace':
                require_membership(db, workspace_id, user.id, roles=ADMIN_ROLES)
            if not api_key:
                raise ValueError('API Key is required')
            credential_id = new_id()
            row = Provider(id=new_id(), workspace_id=workspace_id,
                owner_user_id=user.id if scope == 'personal' else None,
                name=name, base_url=base_url, credential_id=credential_id,
                active=True)
            db.add(Credential(id=credential_id, workspace_id=workspace_id, backend='encrypted',
                handle='encrypted://' + str(credential_id), scope={'workspace_id': str(workspace_id)},
                status='active', created_at=utc_now()))
            db.flush()
            db.add(row)
            db.flush()
            db.add(StoredKey(credential_id=credential_id, provider_id=row.id, base_url=base_url,
                             encrypted_key=encrypt(api_key, credential_id)))
            db.flush()
        row.name = name
        if row.base_url != base_url:
            # Destination changes also require an explicit replacement credential.
            if not api_key:
                raise ValueError('Changing API address requires a replacement Key')
            row.base_url = base_url
            credential_id = new_id()
            db.add(Credential(id=credential_id, workspace_id=workspace_id, backend='encrypted',
                handle='encrypted://' + str(credential_id), scope={'workspace_id': str(workspace_id)},
                status='active', created_at=utc_now()))
            db.flush()
            db.add(StoredKey(credential_id=credential_id, provider_id=row.id, base_url=base_url,
                             encrypted_key=encrypt(api_key, credential_id)))
            row.credential_id = credential_id
            db.flush()
            for link in db.scalars(select(Link).where(Link.provider_id == row.id, Link.active.is_(True))):
                profile = db.get(Profile, link.profile_id)
                old = db.get(Version, profile.current_version_id)
                new_version(db, row, profile, old.model_name)
        if api_key:
            for secret in db.scalars(select(StoredKey).where(StoredKey.provider_id == row.id, StoredKey.base_url == base_url)):
                secret.encrypted_key = encrypt(api_key, secret.credential_id)
        db.flush()
        audit(db, workspace_id, user.id, 'provider.saved', 'model_provider', str(row.id))
        return view(db, row)


def new_version(db: Session, provider: Provider, profile: Profile, model_name: str) -> Version:
    """Append a model version and advance related defaults without changing published Agents.

    Called inside the locked provider transaction; existing Session/Run references stay fixed."""
    old = db.get(Version, profile.current_version_id) if profile.current_version_id else None
    options = {'protocol': 'openai_chat_completions', 'base_url': provider.base_url}
    version = Version(id=new_id(), workspace_id=provider.workspace_id, profile_id=profile.id,
        version=old.version + 1 if old else 1, model_name=model_name, options=options,
        credential_reference_id=provider.credential_id,
        content_hash=content_hash({'model_name': model_name, 'options': options,
                                  'credential_reference_id': str(provider.credential_id)}), created_at=utc_now())
    db.add(version)
    db.flush()
    profile.current_version_id = version.id
    for default in db.scalars(select(Default).where(Default.version_id.in_(select(Version.id).where(Version.profile_id == profile.id)))):
        default.version_id = version.id
    return version


def save_model(db: Session, principal: Principal, workspace_id: UUID, provider_id: UUID, model_name: str, profile_id: UUID | None = None) -> dict[str, str]:
    """Create a provider-bound profile or append its next version after management authorization.

    Unknown, disabled or differently owned profiles raise NotFound; versions are never rewritten."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        provider = provider_access(db, workspace_id, user.id, provider_id, manage=True)
        if profile_id:
            link = db.get(Link, profile_id)
            if not link or link.provider_id != provider.id or not link.active:
                raise NotFound('Model unavailable')
            profile = db.get(Profile, profile_id)
        else:
            profile = Profile(id=new_id(), workspace_id=workspace_id, name='configured-' + str(new_id()),
                provider=provider.name, created_by=user.id, created_at=utc_now())
            db.add(profile)
            db.flush()
            db.add(Link(profile_id=profile.id, provider_id=provider.id, active=True))
        version = new_version(db, provider, profile, model_name)
        audit(db, workspace_id, user.id, 'provider.model_saved', 'model_profile', str(profile.id))
        return {'id': str(profile.id), 'version_id': str(version.id)}


def disable(db: Session, principal: Principal, workspace_id: UUID, provider_id: UUID, profile_id: UUID | None = None) -> None:
    """Soft-disable a provider or model and clear every affected default atomically.

    Historical versions remain traceable. Provider disablement revokes all its credential
    references; it cannot recall requests already received by the remote supplier."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        provider = provider_access(db, workspace_id, user.id, provider_id, manage=True)
        links = list(db.scalars(select(Link).where(Link.provider_id == provider.id)))
        if profile_id:
            links = [link for link in links if link.profile_id == profile_id]
            if not links:
                raise NotFound('Model unavailable')
        else:
            provider.active = False
            for secret in db.scalars(select(StoredKey).where(StoredKey.provider_id == provider.id)):
                db.get(Credential, secret.credential_id).status = 'revoked'
        for link in links:
            link.active = False
            version_ids = select(Version.id).where(Version.profile_id == link.profile_id)
            for item in db.scalars(select(Default).where(Default.version_id.in_(version_ids))):
                db.delete(item)
        audit(db, workspace_id, user.id, 'provider.disabled', 'model_provider', str(provider.id))


def set_default(db: Session, principal: Principal, workspace_id: UUID, scope: str, version_id: UUID | None) -> None:
    """Set or clear the personal/space default to an authorized current model version.

    Space defaults require an administrator and cannot use a personal provider. No existing
    AgentVersion, Session or Run is modified; invalid versions raise NotFound or Conflict."""
    with db.begin():
        user, _ = context(db, principal, workspace_id)
        if scope == 'workspace':
            require_membership(db, workspace_id, user.id, roles=ADMIN_ROLES)
        key = 'workspace' if scope == 'workspace' else str(user.id)
        row = db.get(Default, (workspace_id, key))
        if version_id:
            version = authorize_model(db, workspace_id, user.id, version_id)
            if db.get(Profile, version.profile_id).current_version_id != version.id:
                raise Conflict('Choose the current model version')
            link = db.get(Link, version.profile_id)
            if scope == 'workspace' and link and db.get(Provider, link.provider_id).owner_user_id:
                raise Forbidden('Personal models cannot be workspace defaults')
            if row:
                row.version_id = version_id
            else:
                db.add(Default(workspace_id=workspace_id, scope_key=key, version_id=version_id))
        elif row:
            db.delete(row)
        audit(db, workspace_id, user.id, 'model.default_changed', 'model_default', key)


class StoredCredentialResolver:
    """Resolve only credentials attached to an authorized, currently running task.

    Encrypted references use the supplied database factory; other backends delegate to the
    injected resolver. Returned CredentialLease contains a five-minute in-memory secret,
    intentionally excluded from repr. Revoked access raises a sanitized platform error.
    """
    def __init__(self, factory: sessionmaker[Session], fallback: CredentialResolver | None):
        self.factory, self.fallback = factory, fallback

    def resolve(self, reference: CredentialRef, *, principal_id: UUID, run_id: UUID) -> CredentialLease:
        """Authorize Run, membership and exact model reference before decrypting or delegating."""
        if reference.backend != 'encrypted':
            if self.fallback is None:
                raise ServiceUnavailable('Credential backend is unavailable')
            return self.fallback.resolve(reference, principal_id=principal_id, run_id=run_id)
        with self.factory() as db, db.begin():
            run = db.get(RunRecord, run_id)
            if not run or run.status != 'running' or run.principal_id != principal_id or str(run.workspace_id) != reference.scope:
                raise Forbidden('Credential unavailable')
            require_workspace(db, run.workspace_id)
            require_membership(db, run.workspace_id, principal_id)
            secret = db.get(StoredKey, reference.id)
            provider = db.get(Provider, secret.provider_id) if secret else None
            if not provider:
                raise NotFound('Credential unavailable')
            provider_access(db, run.workspace_id, principal_id, provider.id)
            version = authorize_model(db, run.workspace_id, principal_id,
                                      UUID(run.config_snapshot['model_profile_version_id']))
            if version.credential_reference_id != reference.id:
                raise Forbidden('Credential unavailable')
            audit(db, run.workspace_id, principal_id, 'credential.resolved', 'credential_reference', str(reference.id))
            return CredentialLease(decrypt(secret), utc_now() + timedelta(minutes=5))
