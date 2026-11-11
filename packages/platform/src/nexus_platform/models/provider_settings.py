"""Scoped model settings and write-only, authenticated credential storage."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from nexus_core.platform import Principal, CredentialRef

from nexus_core.platform import new_id, utc_now
from nexus_platform.configuration import DatabaseConfigurationError, credential_encryption_key
from nexus_platform.errors import Forbidden, NotFound, ServiceUnavailable, Conflict
from nexus_platform.identity.service import resolve_user, require_tenant, require_membership
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.models.service import content_hash
from nexus_platform.models.ports import CredentialLease, CredentialResolver
from nexus_platform.persistence.models import (
    ModelProviderRecord as Provider, ProviderModelRecord as Link, ModelDefaultRecord as Default,
    CredentialReferenceRecord as Credential, ModelProfileRecord as Profile,
    ModelProfileVersionRecord as Version, RunRecord, ProviderCredentialRecord as StoredKey,
    UserRecord, MembershipRecord, MemoryCaptureSettingsRecord,
)
from nexus_platform.tenants.service import ADMIN_ROLES
from nexus_platform.authz.audit import audit
from nexus_platform.tenants.policies import personal_models_allowed


def cipher() -> Fernet:
    """Load the deployment Fernet key; raise ServiceUnavailable rather than generate a fallback.

    API and worker must share this key. Its value never leaves the credential adapter."""
    try:
        key = credential_encryption_key()
        if key is None:
            raise ServiceUnavailable('Credential encryption key is not configured correctly')
        return Fernet(key.encode('ascii'))
    except (DatabaseConfigurationError, ValueError, UnicodeError):
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


def context(db: Session, principal: Principal, tenant_id: UUID) -> tuple[UserRecord, MembershipRecord]:
    """Resolve the authenticated user and active Tenant membership in the caller transaction."""
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    membership = require_membership(db, tenant_id, user.id)
    return user, membership


def provider_access(db: Session, tenant_id: UUID, user_id: UUID, provider_id: UUID, *, manage: bool = False) -> Provider:
    """Require an active provider in this Tenant and the caller’s personal scope.

    Reads hide private/disabled resources as NotFound. Management of shared providers
    additionally requires an administrator and locks the row for consistent updates."""
    row = db.scalar(select(Provider).where(Provider.id == provider_id).with_for_update()) if manage else db.get(Provider, provider_id)
    if not row or row.tenant_id != tenant_id or not row.active:
        raise NotFound('Provider unavailable')
    if row.owner_user_id is not None and row.owner_user_id != user_id:
        raise NotFound('Provider unavailable')
    if row.owner_user_id is not None and not personal_models_allowed(db, tenant_id):
        raise Forbidden('Your enterprise does not allow personal models')
    if manage and row.owner_user_id is None:
        require_membership(db, tenant_id, user_id)
        require_api_permission(db, tenant_id, user_id, "models:manage")
    return row


def authorize_model(db: Session, tenant_id: UUID, user_id: UUID, version_id: UUID) -> Version:
    """Check version, current credential, provider ownership and model availability.

    Historical versions remain valid until explicitly disabled. This check is shared by
    publication, Session/Run creation and execution so an Agent cannot grant personal Key access."""
    version = db.get(Version, version_id)
    if not version or version.tenant_id != tenant_id:
        raise NotFound('Model unavailable')
    if version.credential_reference_id:
        ref = db.get(Credential, version.credential_reference_id)
        if not ref or ref.tenant_id != tenant_id or ref.status != 'active':
            raise NotFound('Model credential unavailable')
        secret = db.get(StoredKey, version.credential_reference_id)
        if secret:
            provider_access(db, tenant_id, user_id, secret.provider_id)
    link = db.get(Link, version.profile_id)
    if link:
        if not link.active:
            raise NotFound('Model unavailable')
        provider_access(db, tenant_id, user_id, link.provider_id)
    return version


@dataclass(frozen=True)
class CaptureModelCall:
    """Everything one memory-capture extraction needs. `lease` holds the owner's key in memory only."""
    model_name: str
    provider: str
    options: dict
    lease: CredentialLease


def owner_model_call(factory: sessionmaker[Session], *, tenant_id: UUID, owner_id: UUID, version_id: UUID,
                     purpose: str, model_type: str | None = None) -> CaptureModelCall:
    """Authorize a model for its owner and resolve the owner's own key for one background call.

    Same checks as `capture_model_call` without the capture settings: active membership, current access
    to the model and its provider, an active encrypted key reference, and, when given, the model type
    (for example `embedding`). Used by memory embeddings (openspec 2026-11-06-memory-evolution D2).
    Audited as `credential.resolved` with `purpose`. Failures are sanitized NotFound.
    """
    with factory() as db, db.begin():
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, owner_id)
        version = authorize_model(db, tenant_id, owner_id, version_id)
        profile = db.get(Profile, version.profile_id)
        if model_type is not None and profile.model_type != model_type:
            raise NotFound('Model unavailable')
        ref = db.get(Credential, version.credential_reference_id) if version.credential_reference_id else None
        if not ref or ref.backend != 'encrypted' or ref.status != 'active' or ref.tenant_id != tenant_id:
            raise NotFound('Model credential unavailable')
        secret = db.get(StoredKey, ref.id)
        if not secret:
            raise NotFound('Model credential unavailable')
        provider_access(db, tenant_id, owner_id, secret.provider_id)
        audit(db, tenant_id, owner_id, 'credential.resolved', 'credential_reference', str(ref.id), {'purpose': purpose})
        return CaptureModelCall(model_name=version.model_name, provider=profile.provider,
                                options=dict(version.options),
                                lease=CredentialLease(decrypt(secret), utc_now() + timedelta(minutes=5)))


def capture_model_call(factory: sessionmaker[Session], *, tenant_id: UUID, owner_id: UUID,
                       version_id: UUID, purpose: str = 'memory.capture',
                       require_enabled: bool = True) -> CaptureModelCall:
    """Authorize the capture model and resolve the owner's own key for one extraction call.

    A Run checks its owner, membership and model grants while it is running. Capture has no running
    Run, so this checks the same things directly: active membership, capture enabled with this exact
    model version, current access to the model and its provider, and an active encrypted key reference.
    Environment-backed keys are not resolved here because they are not tied to a user. Each call is
    audited as `credential.resolved` with purpose `memory.capture`. Failures are sanitized NotFound.
    """
    with factory() as db, db.begin():
        require_tenant(db, tenant_id)
        require_membership(db, tenant_id, owner_id)
        settings = db.get(MemoryCaptureSettingsRecord, (tenant_id, owner_id))
        # Consolidation a member asked for runs with the saved capture model even when automatic capture is off.
        if (settings is None or (require_enabled and not settings.enabled)
                or settings.model_profile_version_id != version_id):
            raise NotFound('Model unavailable')
        version = authorize_model(db, tenant_id, owner_id, version_id)
        ref = db.get(Credential, version.credential_reference_id) if version.credential_reference_id else None
        if not ref or ref.backend != 'encrypted' or ref.status != 'active' or ref.tenant_id != tenant_id:
            raise NotFound('Model credential unavailable')
        secret = db.get(StoredKey, ref.id)
        if not secret:
            raise NotFound('Model credential unavailable')
        provider_access(db, tenant_id, owner_id, secret.provider_id)
        profile = db.get(Profile, version.profile_id)
        audit(db, tenant_id, owner_id, 'credential.resolved', 'credential_reference', str(ref.id),
              {'purpose': purpose})
        return CaptureModelCall(model_name=version.model_name, provider=profile.provider,
                                options=dict(version.options),
                                lease=CredentialLease(decrypt(secret), utc_now() + timedelta(minutes=5)))


def view(db: Session, row: Provider) -> dict[str, object]:
    """Project public provider metadata and active current model versions; never expose a Key."""
    models = []
    for link in db.scalars(select(Link).where(Link.provider_id == row.id, Link.active.is_(True))):
        profile = db.get(Profile, link.profile_id)
        version = db.get(Version, profile.current_version_id)
        models.append({'id': str(profile.id), 'name': version.model_name, 'model_type': profile.model_type,
                       'version_id': str(version.id), 'version': version.version, 'options': version.options})
    return {'id': str(row.id), 'name': row.name, 'base_url': row.base_url,
            'scope': 'personal' if row.owner_user_id else 'tenant',
            'key_configured': True, 'key_mask': '••••••••', 'models': models}


def list_settings(db: Session, principal: Principal, tenant_id: UUID) -> dict[str, object]:
    """Return only visible providers, authorized defaults and the caller’s management capability.

    Unavailable defaults are omitted; no private configuration is returned to space administrators."""
    with db.begin():
        user, membership = context(db, principal, tenant_id)
        rows = db.scalars(select(Provider).where(Provider.tenant_id == tenant_id, Provider.active.is_(True)))
        providers = [view(db, row) for row in rows if row.owner_user_id in (None, user.id)]
        defaults: dict[str, dict[str, str]] = {}
        scopes = {str(user.id): 'personal', 'tenant': 'tenant'}
        for item in db.scalars(select(Default).where(Default.tenant_id == tenant_id, Default.scope_key.in_(list(scopes)))):
            try:
                authorize_model(db, tenant_id, user.id, item.version_id)
                defaults.setdefault(scopes[item.scope_key], {})[item.model_type] = str(item.version_id)
            except (NotFound, Forbidden):
                pass
        return {'providers': providers, 'defaults': defaults, 'can_manage_tenant': membership.role in ADMIN_ROLES}


def save_provider(db: Session, principal: Principal, tenant_id: UUID, *, name: str, base_url: str, scope: str, api_key: str | None, provider_id: UUID | None = None) -> dict[str, object]:
    """Create or update an authorized provider in one transaction and return public metadata.

    Address changes require a replacement Key and new references, preserving historical
    destinations. Same-address replacement rotates credentials for subsequent resolutions.
    Missing encryption configuration fails without persisting plaintext."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        if provider_id:
            row = provider_access(db, tenant_id, user.id, provider_id, manage=True)
            if scope != ('personal' if row.owner_user_id else 'tenant'):
                raise Conflict('Provider scope cannot be changed')
        else:
            if scope == 'tenant':
                require_membership(db, tenant_id, user.id)
                require_api_permission(db, tenant_id, user.id, "models:manage")
            elif not personal_models_allowed(db, tenant_id):
                raise Forbidden('Your enterprise does not allow personal models')
            if not api_key:
                raise ValueError('API Key is required')
            credential_id = new_id()
            row = Provider(id=new_id(), tenant_id=tenant_id,
                owner_user_id=user.id if scope == 'personal' else None,
                name=name, base_url=base_url, credential_id=credential_id,
                active=True)
            db.add(Credential(id=credential_id, tenant_id=tenant_id, backend='encrypted',
                handle='encrypted://' + str(credential_id), scope={'tenant_id': str(tenant_id)},
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
            db.add(Credential(id=credential_id, tenant_id=tenant_id, backend='encrypted',
                handle='encrypted://' + str(credential_id), scope={'tenant_id': str(tenant_id)},
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
        audit(db, tenant_id, user.id, 'provider.saved', 'model_provider', str(row.id))
        return view(db, row)


def new_version(db: Session, provider: Provider, profile: Profile, model_name: str, model_options: dict | None = None) -> Version:
    """Append a model version and advance related defaults without changing published Agents.

    Called inside the locked provider transaction; existing Session/Run references stay fixed."""
    old = db.get(Version, profile.current_version_id) if profile.current_version_id else None
    options = dict(old.options) if old else {'protocol': 'openai_chat_completions'}
    options.update(model_options or {})
    options['base_url'] = provider.base_url
    version = Version(id=new_id(), tenant_id=provider.tenant_id, profile_id=profile.id,
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


def save_model(db: Session, principal: Principal, tenant_id: UUID, provider_id: UUID, model_name: str, profile_id: UUID | None = None, model_options: dict | None = None, model_type: str = 'chat') -> dict[str, str]:
    """Create a provider-bound profile or append its next version after management authorization.

    Unknown, disabled or differently owned profiles raise NotFound; versions are never rewritten.
    The capability type is fixed when the profile is created; changing it on edit is a Conflict."""
    model_options = validate_model_options(model_options or {})
    model_type = validate_model_type(model_type)
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        provider = provider_access(db, tenant_id, user.id, provider_id, manage=True)
        if profile_id:
            link = db.get(Link, profile_id)
            if not link or link.provider_id != provider.id or not link.active:
                raise NotFound('Model unavailable')
            profile = db.get(Profile, profile_id)
            if profile.model_type != model_type:
                raise Conflict('Model type cannot be changed; add a new model instead')
        else:
            profile = Profile(id=new_id(), tenant_id=tenant_id, name='configured-' + str(new_id()),
                provider=provider.name, model_type=model_type, created_by=user.id, created_at=utc_now())
            db.add(profile)
            db.flush()
            db.add(Link(profile_id=profile.id, provider_id=provider.id, active=True))
        version = new_version(db, provider, profile, model_name, model_options)
        audit(db, tenant_id, user.id, 'provider.model_saved', 'model_profile', str(profile.id), {'model_type': model_type})
        return {'id': str(profile.id), 'version_id': str(version.id)}


def disable(db: Session, principal: Principal, tenant_id: UUID, provider_id: UUID, profile_id: UUID | None = None) -> None:
    """Soft-disable a provider or model and clear every affected default atomically.

    Historical versions remain traceable. Provider disablement revokes all its credential
    references; it cannot recall requests already received by the remote supplier."""
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        provider = provider_access(db, tenant_id, user.id, provider_id, manage=True)
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
        audit(db, tenant_id, user.id, 'provider.disabled', 'model_provider', str(provider.id))


def set_default(db: Session, principal: Principal, tenant_id: UUID, scope: str, version_id: UUID | None, model_type: str = 'chat') -> None:
    """Set or clear the personal/space default for one model type to an authorized current version.

    Space defaults require an administrator and cannot use a personal provider. A version can only
    fill the slot of its own type. No existing AgentVersion, Session or Run is modified; invalid
    versions raise NotFound or Conflict."""
    model_type = validate_model_type(model_type)
    with db.begin():
        user, _ = context(db, principal, tenant_id)
        if scope == 'tenant':
            require_membership(db, tenant_id, user.id)
            require_api_permission(db, tenant_id, user.id, "models:manage")
        key = 'tenant' if scope == 'tenant' else str(user.id)
        row = db.get(Default, (tenant_id, key, model_type))
        if version_id:
            version = authorize_model(db, tenant_id, user.id, version_id)
            profile = db.get(Profile, version.profile_id)
            if profile.current_version_id != version.id:
                raise Conflict('Choose the current model version')
            if profile.model_type != model_type:
                raise Conflict('Model type does not match this default')
            link = db.get(Link, version.profile_id)
            if scope == 'tenant' and link and db.get(Provider, link.provider_id).owner_user_id:
                raise Forbidden('Personal models cannot be tenant defaults')
            if row:
                row.version_id = version_id
            else:
                db.add(Default(tenant_id=tenant_id, scope_key=key, model_type=model_type, version_id=version_id))
        elif row:
            db.delete(row)
        audit(db, tenant_id, user.id, 'model.default_changed', 'model_default', key, {'model_type': model_type})


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
            if not run or run.status != 'running' or run.principal_id != principal_id or str(run.tenant_id) != reference.scope:
                raise Forbidden('Credential unavailable')
            require_tenant(db, run.tenant_id)
            require_membership(db, run.tenant_id, principal_id)
            secret = db.get(StoredKey, reference.id)
            provider = db.get(Provider, secret.provider_id) if secret else None
            if not provider:
                raise NotFound('Credential unavailable')
            provider_access(db, run.tenant_id, principal_id, provider.id)
            allowed_versions = [run.config_snapshot['model_profile_version_id'],
                *run.config_snapshot.get('budgets', {}).get('behavior', {}).get('fallback_models', [])]
            versions = [authorize_model(db, run.tenant_id, principal_id, UUID(identifier)) for identifier in allowed_versions]
            if not any(version.credential_reference_id == reference.id for version in versions):
                raise Forbidden('Credential unavailable')
            audit(db, run.tenant_id, principal_id, 'credential.resolved', 'credential_reference', str(reference.id))
            return CredentialLease(decrypt(secret), utc_now() + timedelta(minutes=5))


# Capability types a configured model can declare. Only 'chat' is executed in this stage; the others
# are stored and shown so that knowledge-base features (roadmap step 6) can use them later.
MODEL_TYPES = ('chat', 'embedding', 'rerank', 'vision', 'speech')


def validate_model_type(value: str) -> str:
    """Accept only the fixed capability types; anything else is a validation error, not a default."""
    if value not in MODEL_TYPES:
        raise ValueError('Unsupported model type')
    return value


def validate_model_options(options: dict) -> dict:
    """Whitelist user-visible protocol settings; addresses and secrets stay provider-owned."""
    allowed = {'protocol', 'stream', 'temperature', 'reasoning_effort', 'text_tools'}
    if set(options) - allowed:
        raise ValueError('Unsupported model option')
    if options.get('protocol', 'openai_chat_completions') not in ('openai_chat_completions', 'openai_responses', 'anthropic_messages'):
        raise ValueError('Unsupported model protocol')
    for name in ('stream', 'text_tools'):
        if name in options and type(options[name]) is not bool:
            raise ValueError('Model switches must be boolean')
    if 'temperature' in options:
        import math
        value = options['temperature']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 2:
            raise ValueError('Temperature must be between 0 and 2')
    if options.get('reasoning_effort', '') not in ('', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'):
        raise ValueError('Unsupported reasoning effort')
    return options
