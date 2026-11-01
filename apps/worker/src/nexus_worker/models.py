"""Application-level authorized fallback resolution; Native transport never imports platform."""
from dataclasses import replace
from uuid import UUID
from nexus_core.native import NativePolicy
from nexus_core.platform import CredentialRef
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.persistence.models import CredentialReferenceRecord, ModelProfileRecord
from nexus_platform.identity.service import require_membership, require_tenant
from nexus_runtimes.native.models.retry import RetryModel
from nexus_runtimes.native.models.routing import RoutedModel


def routed_context(context, factory, identifier: str):
    """Authorize a model version now and return the Run context rebuilt for that version.

    Called at construction time, so a grant revoked mid-Run stops the next use of the version.
    Raises PlatformError when the version, its credential, or the caller's membership is unavailable.
    """
    with factory() as db, db.begin():
        require_tenant(db, context.tenant_id)
        require_membership(db, context.tenant_id, context.principal_id)
        version = authorize_model(db, context.tenant_id, context.principal_id, UUID(identifier))
        profile = db.get(ModelProfileRecord, version.profile_id)
        ref = db.get(CredentialReferenceRecord, version.credential_reference_id) if version.credential_reference_id else None
        credential = CredentialRef(ref.id, ref.backend, ref.handle, str(context.tenant_id)) if ref else None
        return replace(context, options=version.options, model_name=version.model_name, provider=profile.provider, credential=credential)


def compaction_model(context, factory, resolver, identifier: str):
    """Build the configured summarizer for context compaction through the same authorized path (P3)."""
    from .native import configured_model
    return configured_model(routed_context(context, factory, identifier), resolver)


def configured_routing(context, factory, resolver):
    """Recheck each fallback version and credential immediately before constructing its client."""
    from .native import configured_model
    policy = NativePolicy(**context.budgets.get('behavior', {}))
    initial = [configured_model(context, resolver)]
    def primary():
        return initial.pop() if initial else configured_model(context, resolver)
    factories = [primary]
    for identifier in policy.fallback_models:
        def fallback(identifier=identifier):
            return configured_model(routed_context(context, factory, identifier), resolver)
        factories.append(fallback)
    return RetryModel(RoutedModel(factories, spring_back_seconds=policy.routing_spring_seconds,
                                         max_retry_delay_seconds=policy.max_retry_delay_seconds), policy)
