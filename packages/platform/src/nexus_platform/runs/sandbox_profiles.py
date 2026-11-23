"""Administrative sandbox profile policy and redacted acceptance diagnostics."""
from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from sqlalchemy.orm import Session

from nexus_core.deployment import DeploymentConfigError
from nexus_core.platform import Principal
from nexus_platform.authz.audit import audit
from nexus_platform.errors import Forbidden, InvalidConfiguration, NotFound, ServiceUnavailable
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.persistence.models import UserRecord
from nexus_platform.tenants.service import ADMIN_ROLES
from nexus_sandbox import acceptance
from nexus_sandbox.settings import (PROFILE_POLICY_FIELDS, SandboxConfig, SandboxSettings,
                                    load_config, save_profile_policy)

from .sandbox_acceptance import DbReportStore
from .tool_gates import profile_facts, unavailable_groups


def _settings(db: Session, principal: Principal, tenant_id: UUID, name: str) -> tuple[UserRecord, SandboxConfig, SandboxSettings]:
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    membership = require_membership(db, tenant_id, user.id)
    if membership.role not in ADMIN_ROLES:
        raise Forbidden('sandbox_admin_required')
    try:
        config = load_config()
    except DeploymentConfigError:
        raise ServiceUnavailable('sandbox_configuration_unavailable') from None
    settings = config.profiles.get(name)
    if settings is None:
        raise NotFound('sandbox_profile_not_found')
    return user, config, settings


def _detail(db: Session, user: UserRecord, config: SandboxConfig, settings: SandboxSettings) -> dict:
    facts = profile_facts(db, config, settings)
    reason = unavailable_groups(facts).get('sandbox', '') if config.enabled else 'sandbox_disabled'
    report = None
    if settings.backend != 'local':
        try:
            report = DbReportStore(db).load(settings)
            if report is None:
                report = acceptance.FileReportStore().load(settings)
        except Exception:
            report = None
    resource_limits = {}
    if settings.backend in ('docker', 'managed'):
        resource_limits = {'cpus': settings.cpus, 'memory_mb': settings.memory_mb, 'pids': settings.pids}
    elif settings.backend == 'bwrap':
        resource_limits = {'memory_mb': settings.memory_mb}
    items = report.get('items') if report else None
    return {
        'name': settings.profile, 'type': settings.backend, 'default': settings.profile == config.default_profile,
        'available': not reason, 'reason': reason, 'editable': user.is_platform_admin,
        'policy': {key: getattr(settings, key) for key in PROFILE_POLICY_FIELDS},
        'network': settings.network if settings.backend != 'local' else None,
        'image': settings.image if settings.backend == 'docker' else None,
        'remote_profile': settings.remote_profile or None,
        'workspace_quota_mb': settings.workspace_quota_mb,
        'limits': resource_limits,
        'background': settings.backend in ('local', 'docker'),
        'build': settings.backend in ('local', 'bwrap', 'docker'),
        'acceptance': ({
            'checked_at': report.get('checked_at'),
            'passed': acceptance.valid(settings, report),
            'items': [{'name': item['name'], 'ok': bool(item['ok'])} for item in (items if isinstance(items, list) else [])
                      if isinstance(item, dict) and isinstance(item.get('name'), str) and 'ok' in item],
        } if report else None),
    }


def profile_detail(db: Session, principal: Principal, tenant_id: UUID, name: str) -> dict:
    """Read a deployment profile's public configuration and last worker-side report."""
    with db.begin():
        return _detail(db, *_settings(db, principal, tenant_id, name))


def update_policy(db: Session, principal: Principal, tenant_id: UUID, name: str, policy: dict) -> dict:
    """Update deployment-wide settings only for platform administrators and audit the policy change."""
    with db.begin():
        user, config, settings = _settings(db, principal, tenant_id, name)
        if not user.is_platform_admin:
            raise Forbidden('sandbox_platform_admin_required')
        try:
            policy = save_profile_policy(settings, policy)
        except DeploymentConfigError:
            raise InvalidConfiguration('sandbox_policy_invalid') from None
        except OSError:
            raise ServiceUnavailable('sandbox_policy_write_failed') from None
        audit(db, tenant_id, user.id, 'sandbox.policy_updated', 'sandbox_profile', name, policy)
        return _detail(db, user, config, replace(settings, **policy))
