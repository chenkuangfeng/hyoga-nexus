"""Administrative sandbox profile policy and redacted acceptance diagnostics."""
from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from sqlalchemy.orm import Session

from nexus_core.deployment import DeploymentConfigError
from nexus_core.platform import Principal
from nexus_core.sandbox import SandboxError
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
        if settings.cgroup_root:
            resource_limits.update(cpus=settings.cpus, pids=settings.pids)
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
        'connection': settings.remote_capabilities or None,
        'hard_disk_quota': bool(settings.quota_mount),
        'hard_process_limits': settings.backend in ('docker', 'managed') or bool(settings.cgroup_root),
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


def connect_profile(db: Session, principal: Principal, tenant_id: UUID, name: str) -> dict:
    """Validate a trusted gateway and bind subsequent execution and acceptance to its exact policy."""
    import re
    import httpx
    from datetime import datetime, timezone
    from urllib.parse import quote
    from nexus_sandbox.backends.remote import RemoteExecutor

    with db.begin():
        user, config, settings = _settings(db, principal, tenant_id, name)
        if not user.is_platform_admin:
            raise Forbidden('sandbox_platform_admin_required')
        if settings.backend != 'managed':
            raise InvalidConfiguration('sandbox_connection_not_supported')
    try:
        executor = RemoteExecutor(settings, '', '')
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
            with client.stream('GET', f'{settings.endpoint}/v1/profiles/{quote(settings.remote_profile)}/capabilities',
                               headers={'Authorization': f'Bearer {executor._token()}'}) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes(4096):
                    body.extend(chunk)
                    if len(body) > 4096:
                        raise ValueError
        import json
        capabilities = json.loads(body)
        if (not isinstance(capabilities, dict)
                or not isinstance(capabilities.get('policy_digest'), str)
                or not re.fullmatch('[a-f0-9]{64}', capabilities['policy_digest'])
                or capabilities.get('provider') not in ('docker', 'e2b', 'cubesandbox')
                or capabilities.get('file_transfer') not in ('snapshot', 'shared_volume')
                or capabilities.get('network') != 'none'
                or capabilities.get('output_capture') != 'bounded'
                or capabilities.get('cleanup') != 'persistent'):
            raise ValueError
        keys = ('policy_digest', 'provider', 'file_transfer', 'background', 'build',
                'network', 'output_capture', 'cleanup', 'template_revision')
        capabilities = {key: capabilities.get(key) for key in keys}
        capabilities['connected_at'] = datetime.now(timezone.utc).isoformat()
        save_profile_policy(settings, {
            **{key: getattr(settings, key) for key in PROFILE_POLICY_FIELDS},
            'remote_policy_digest': capabilities['policy_digest'], 'remote_capabilities': capabilities,
        })
    except (httpx.HTTPError, ValueError, OSError, DeploymentConfigError, SandboxError):
        raise ServiceUnavailable('sandbox_connection_failed') from None
    with db.begin():
        audit(db, tenant_id, user.id, 'sandbox.connected', 'sandbox_profile', name,
              {'policy_digest': capabilities['policy_digest']})
    return profile_detail(db, principal, tenant_id, name)


def gateway_operations(db: Session, principal: Principal, tenant_id: UUID, name: str,
                       request_id: str | None = None) -> dict:
    """Read node lifecycle status or retry cleanup; restrict global node operations to platform admins."""
    import httpx
    import json
    import re
    from urllib.parse import quote
    from nexus_sandbox.backends.remote import RemoteExecutor

    with db.begin():
        user, config, settings = _settings(db, principal, tenant_id, name)
        if not user.is_platform_admin:
            raise Forbidden('sandbox_platform_admin_required')
        if settings.backend != 'managed':
            raise InvalidConfiguration('sandbox_connection_not_supported')
    path = f'{settings.endpoint}/v1/profiles/{quote(settings.remote_profile)}/executions'
    if request_id is not None:
        if not re.fullmatch('[a-f0-9]{32}', request_id):
            raise InvalidConfiguration('sandbox_execution_invalid')
        path += f'/{request_id}/cleanup'
    try:
        executor = RemoteExecutor(settings, '', '')
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=60) as client:
            with client.stream('GET' if request_id is None else 'POST', path,
                               headers={'Authorization': f'Bearer {executor._token()}'}) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes(4096):
                    content.extend(chunk)
                    if len(content) > 65536:
                        raise ValueError
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError
    except (ValueError, httpx.HTTPError, SandboxError):
        raise ServiceUnavailable('sandbox_gateway_unavailable') from None
    if request_id is not None:
        with db.begin():
            audit(db, tenant_id, user.id, 'sandbox.cleanup_requested', 'sandbox_profile', name,
                  {'request_id': request_id})
    return result


def provider_settings(db: Session, principal: Principal, tenant_id: UUID, name: str,
                      values: dict | None = None) -> dict:
    """Manage encrypted gateway provider credentials through a platform-admin-only endpoint."""
    import httpx
    import json
    from urllib.parse import quote
    from nexus_sandbox.backends.remote import RemoteExecutor

    with db.begin():
        user, config, settings = _settings(db, principal, tenant_id, name)
        if not user.is_platform_admin:
            raise Forbidden('sandbox_platform_admin_required')
        if settings.backend != 'managed':
            raise InvalidConfiguration('sandbox_connection_not_supported')
    try:
        executor = RemoteExecutor(settings, '', '')
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=15) as client:
            with client.stream(
                'GET' if values is None else 'PUT',
                f'{settings.endpoint}/v1/profiles/{quote(settings.remote_profile)}/provider',
                headers={'Authorization': f'Bearer {executor._token()}'}, json=values,
            ) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes(4096):
                    content.extend(chunk)
                    if len(content) > 4096:
                        raise ValueError
            public = json.loads(content)
            if (not isinstance(public, dict) or set(public) != {'type', 'template', 'domain', 'revision', 'has_api_key'}
                    or public['type'] not in ('docker', 'e2b', 'cubesandbox')
                    or type(public['has_api_key']) is not bool):
                raise ValueError
    except (httpx.HTTPError, ValueError, SandboxError):
        raise ServiceUnavailable('sandbox_provider_configuration_failed') from None
    if values is not None:
        save_profile_policy(settings, {**{key: getattr(settings, key) for key in PROFILE_POLICY_FIELDS},
                                       'remote_policy_digest': '', 'remote_capabilities': {}})
        with db.begin():
            audit(db, tenant_id, user.id, 'sandbox.provider_updated', 'sandbox_profile', name,
                  {'provider': public['type'], 'revision': public['revision']})
    return public
