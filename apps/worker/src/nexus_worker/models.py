"""Application-level authorized fallback resolution; Native transport never imports platform."""
from dataclasses import replace
from uuid import UUID
from nexus_core.native import NativePolicy
from nexus_core.platform import CredentialRef
from nexus_platform.models.provider_settings import authorize_model
from nexus_platform.persistence.models import CredentialReferenceRecord, ModelProfileRecord
from nexus_platform.identity.service import require_membership, require_workspace
from nexus_runtimes.native.models.retry import RetryModel
from nexus_runtimes.native.models.routing import RoutedModel


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
            with factory() as db, db.begin():
                require_workspace(db, context.workspace_id)
                require_membership(db, context.workspace_id, context.principal_id)
                version = authorize_model(db, context.workspace_id, context.principal_id, UUID(identifier))
                profile = db.get(ModelProfileRecord, version.profile_id)
                ref = db.get(CredentialReferenceRecord, version.credential_reference_id) if version.credential_reference_id else None
                credential = CredentialRef(ref.id, ref.backend, ref.handle, str(context.workspace_id)) if ref else None
                routed = replace(context, options=version.options, model_name=version.model_name, provider=profile.provider, credential=credential)
            return configured_model(routed, resolver)
        factories.append(fallback)
    return RetryModel(RoutedModel(factories, spring_back_seconds=policy.routing_spring_seconds), policy)
