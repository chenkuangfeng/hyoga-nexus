"""Authenticated user settings. Secrets are accepted only in write-only fields."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.http.admin_routes import tenant_admin_route
from nexus_core.platform import Principal, utc_now
from nexus_core.runtime import ModelRequest, ModelMessage, RuntimeFault
from nexus_platform.models import provider_settings as settings
from nexus_platform.persistence.models import ModelProfileRecord, ModelProfileVersionRecord
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.identity.service import require_membership
from nexus_runtimes.native.models.network import validate_url, provider_client
from nexus_runtimes.native.models.openai_compatible import OpenAICompatibleModel

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}', tags=['Model settings'])


class ProviderInput(BaseModel):
    """Public supplier configuration with a write-only, optional replacement secret."""

    name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=1, max_length=512)
    scope: Literal['personal', 'tenant'] = 'personal'
    api_key: SecretStr | None = None


ModelType = Literal['chat', 'embedding', 'rerank', 'vision', 'speech']


class ModelInput(BaseModel):
    """Supplier model identifier; edits append versions rather than rewriting history.

    The capability type is set when the model is created and cannot change on later edits."""

    name: str = Field(min_length=1, max_length=160)
    options: dict[str, object] = Field(default_factory=dict)
    model_type: ModelType = 'chat'


class DefaultInput(BaseModel):
    """Scoped default preference for one model type; a null version clears that preference."""

    scope: Literal['personal', 'tenant'] = 'personal'
    model_type: ModelType = 'chat'
    version_id: UUID | None = None


class DraftTestInput(BaseModel):
    """Connection test for an unsaved configuration; nothing is persisted.

    `provider_id` lets an edit reuse the stored Key when `api_key` is omitted. A replacement
    address always needs a replacement Key, as on save."""

    scope: Literal['personal', 'tenant'] = 'personal'
    base_url: str = Field(min_length=1, max_length=512)
    model_name: str = Field(min_length=1, max_length=160)
    model_type: ModelType = 'chat'
    options: dict[str, object] = Field(default_factory=dict)
    provider_id: UUID | None = None
    api_key: SecretStr | None = None


class AgentInput(BaseModel):
    """Minimal Native Agent configuration; omitted model selects authorized defaults."""

    name: str = Field(min_length=1, max_length=160)
    instructions: str = Field(default='You are a helpful assistant.', max_length=20000)
    model_profile_version_id: UUID | None = None


def provider_values(body: ProviderInput) -> dict[str, object]:
    """Validate public configuration and one-time Key without reflecting secret input in errors."""
    if not body.name.strip():
        raise ValueError('Provider name is required')
    key = body.api_key.get_secret_value() if body.api_key else None
    if key is not None and (not key.strip() or len(key) > 8192 or any(ord(c) < 32 for c in key)):
        raise ValueError('Invalid API Key')
    try:
        url = validate_url(body.base_url)
    except RuntimeFault:
        raise ValueError('API address is not permitted; use a public HTTPS endpoint') from None
    return dict(name=body.name.strip(), base_url=url, scope=body.scope, api_key=key)


@tenant_admin_route(router, '/model-settings', methods=['GET'])
def list_settings(tenant_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Return the authenticated caller’s visible models and defaults in the requested Tenant."""
    return settings.list_settings(db, principal, tenant_id)


@tenant_admin_route(router, '/model-settings/providers', methods=['POST'], status_code=201)
def create_provider(tenant_id: UUID, body: ProviderInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Accept a write-only Key and return a masked, scoped provider after encrypted persistence."""
    return settings.save_provider(db, principal, tenant_id, **provider_values(body))


@tenant_admin_route(router, '/model-settings/providers/{provider_id}', methods=['PUT'])
def update_provider(tenant_id: UUID, provider_id: UUID, body: ProviderInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Update metadata or rotate the Key after owner/administrator authorization."""
    return settings.save_provider(db, principal, tenant_id, provider_id=provider_id, **provider_values(body))


@tenant_admin_route(router, '/model-settings/providers/{provider_id}', methods=['DELETE'])
def delete_provider(tenant_id: UUID, provider_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Disable the provider and invalidate its defaults; historical configuration is retained."""
    settings.disable(db, principal, tenant_id, provider_id)
    return {'status': 'disabled'}


@tenant_admin_route(router, '/model-settings/providers/{provider_id}/models', methods=['POST'], status_code=201)
def add_model(tenant_id: UUID, provider_id: UUID, body: ModelInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Create an immutable configured model under a manageable provider."""
    return settings.save_model(db, principal, tenant_id, provider_id, model_name(body.name), model_options=body.options, model_type=body.model_type)


def model_name(value: str) -> str:
    """Normalize the supplier model identifier; reject empty values without invoking the supplier."""
    if not value.strip():
        raise ValueError('Model name is required')
    return value.strip()


@tenant_admin_route(router, '/model-settings/providers/{provider_id}/models/{profile_id}', methods=['PUT'])
def edit_model(tenant_id: UUID, provider_id: UUID, profile_id: UUID, body: ModelInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Append a model version; preserve already published AgentVersion references."""
    return settings.save_model(db, principal, tenant_id, provider_id, model_name(body.name), profile_id, model_options=body.options, model_type=body.model_type)


@tenant_admin_route(router, '/model-settings/providers/{provider_id}/models/{profile_id}', methods=['DELETE'])
def delete_model(tenant_id: UUID, provider_id: UUID, profile_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Disable this model and clear its defaults without deleting historical runs."""
    settings.disable(db, principal, tenant_id, provider_id, profile_id)
    return {'status': 'disabled'}


@tenant_admin_route(router, '/model-settings/default', methods=['PUT'])
def set_default(tenant_id: UUID, body: DefaultInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Set or clear an authorized personal/space preference for one model type.

    Only chat defaults feed Agent creation in this stage."""
    settings.set_default(db, principal, tenant_id, body.scope, body.version_id, body.model_type)
    return {'status': 'saved'}


@tenant_admin_route(router, '/model-settings/agents', methods=['POST'], status_code=201)
def create_native_agent(tenant_id: UUID, body: AgentInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Create and publish a Native Agent using explicit, personal or space-default selection.

    Selection never mutates existing Agents or sessions. No tools are implicitly granted."""
    from nexus_platform.agents.service import create_agent, publish_agent
    with db.begin():
        user, _ = settings.context(db, principal, tenant_id)
        selected = body.model_profile_version_id
        if selected is None:
            for scope in (str(user.id), 'tenant'):
                row = db.get(settings.Default, (tenant_id, scope, 'chat'))
                if row:
                    try:
                        settings.authorize_model(db, tenant_id, user.id, row.version_id)
                        selected = row.version_id
                        break
                    except NotFound:
                        continue
        if selected is None:
            raise ValueError('Select a model or configure a default first')
        settings.authorize_model(db, tenant_id, user.id, selected)
        from nexus_platform.runs.settings import view as native_preferences
        preferences = native_preferences(db, user.id, tenant_id)['settings']
        budgets = preferences['budgets'] | {'behavior': preferences['behavior']}
        bindings = [{'kind': 'tool', 'resource_id': name, 'resource_version_id': 'v1',
            'source_tenant_id': tenant_id, 'config': {}} for name in preferences['behavior']['enabled_tools']]
    agent = create_agent(db, principal, tenant_id, name=body.name, description='', runtime_type='native',
        instructions=body.instructions, model_profile_version_id=selected, budgets=budgets, bindings=bindings)
    version = publish_agent(db, principal, tenant_id, agent.id)
    return {'id': str(agent.id), 'published_version_id': str(version.id), 'name': agent.name}


UNSUPPORTED_TYPE_MESSAGE = '该模型类型的连接测试将在知识库阶段提供'
DEFAULT_FAILURE_MESSAGE = '连接未通过，请检查地址、模型名称和 Key'
#: Safe, fixed explanations per stable fault code; supplier text is never echoed.
CONNECTION_FAILURE_MESSAGES = {
    'model_authentication_failed': '服务商拒绝了 Key：请确认 API Key 正确、未过期，且有该模型的访问权限',
    'model_request_rejected': '服务商拒绝了请求：请检查模型名称，以及接口地址是否完整（多数服务商以 /v1 结尾）',
    'model_quota_exhausted': '账户额度不足，请在服务商控制台充值或更换 Key',
    'model_rate_limited': '服务商限流，请稍后重试',
    'model_timeout': '连接超时，请检查网络或稍后重试',
    'model_provider_unavailable': '无法连接到服务商：请检查网络、域名是否可解析，或稍后重试',
    'model_destination_denied': ('接口地址解析到了内网或保留地址，已被拦截。使用代理的 fake-ip 模式时请对该域名直连；'
                                 '内网服务需在 configs/nexus.toml 的 [model_network].private_host_allowlist 中放行'),
    'model_stream_invalid': '服务商的响应不符合所选接口协议，请检查接口协议与地址',
    'model_response_failed': '服务商返回了无法识别的错误，请检查地址与模型名称',
    'model_configuration_invalid': '模型配置无效，请检查接口地址与协议',
}
DRAFT_TEST_COOLDOWN = timedelta(seconds=10)
# Draft tests have no provider row to rate-limit, so they are limited per user in this process.
# Multi-process deployments get a looser bound; the per-provider limit above still applies to saved models.
draft_test_started: dict[tuple[UUID, UUID], datetime] = {}


async def check_connection(*, key: str, base_url: str, model_name: str, options: dict[str, object], model_type: str) -> dict[str, object]:
    """Run one bounded streaming request and return a sanitized result.

    Only chat models are executed in this stage; other types return `unsupported_for_type` without
    contacting the supplier. Responses carry no generated text and no raw supplier error."""
    if model_type != 'chat':
        return {'ok': False, 'code': 'unsupported_for_type', 'message': UNSUPPORTED_TYPE_MESSAGE}
    model = None
    try:
        if options.get('protocol', 'openai_chat_completions') == 'openai_chat_completions':
            model = OpenAICompatibleModel(model=model_name, api_key=key, base_url=base_url,
                                         timeout=12, http_client=provider_client(base_url, timeout=12), options=options)
        else:
            from nexus_runtimes.native.models.factory import create_model
            model = create_model(model=model_name, api_key=key, options=options, timeout=12)
        async with asyncio.timeout(15):
            async for _ in model.stream(ModelRequest((ModelMessage('user', 'Reply OK.'),), (), 32)):
                pass
        return {'ok': True, 'message': '连接成功，流式响应正常'}
    except RuntimeFault as exc:
        return {'ok': False, 'code': exc.code, 'message': CONNECTION_FAILURE_MESSAGES.get(exc.code, DEFAULT_FAILURE_MESSAGE)}
    except Exception:
        return {'ok': False, 'code': 'model_provider_unavailable', 'message': '连接未通过，请检查配置或稍后重试'}
    finally:
        if model:
            await model.close()


@tenant_admin_route(router, '/model-settings/providers/{provider_id}/models/{profile_id}/test', methods=['POST'])
async def test_connection(tenant_id: UUID, provider_id: UUID, profile_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Test an authorized saved model with a bounded minimal streaming request.

    The supplier may charge for the request. Per-provider tests are limited to one start
    every ten seconds and a fifteen-second total deadline. Responses omit generated content
    and raw supplier errors; the client is closed even on timeout or request cancellation."""
    with db.begin():
        user, _ = settings.context(db, principal, tenant_id)
        provider = settings.provider_access(db, tenant_id, user.id, provider_id, manage=True)
        link = db.get(settings.Link, profile_id)
        if not link or link.provider_id != provider.id or not link.active:
            raise NotFound('Model unavailable')
        if provider.last_test_at and provider.last_test_at.replace(tzinfo=timezone.utc) > utc_now() - DRAFT_TEST_COOLDOWN:
            raise Conflict('Please wait 10 seconds before testing again')
        provider.last_test_at = utc_now()
        profile = db.get(ModelProfileRecord, profile_id)
        version = db.get(ModelProfileVersionRecord, profile.current_version_id)
        key = settings.decrypt(db.get(settings.StoredKey, version.credential_reference_id))
        base_url, name = version.options['base_url'], version.model_name
        audit(db, tenant_id, user.id, 'provider.connection_test', 'model_provider', str(provider.id))
    return await check_connection(key=key, base_url=base_url, model_name=name, options=dict(version.options), model_type=profile.model_type)


@tenant_admin_route(router, '/model-settings/test', methods=['POST'])
async def test_draft(tenant_id: UUID, body: DraftTestInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Test the configuration currently in the form, before anything is saved.

    Authorization matches saving: an edit needs management of the existing provider; a new
    shared provider needs `models:manage`. Errors never echo the Key, the address or supplier text."""
    options = settings.validate_model_options(dict(body.options))
    model_type = settings.validate_model_type(body.model_type)
    try:
        base_url = validate_url(body.base_url)
    except RuntimeFault:
        raise ValueError('API address is not permitted; use a public HTTPS endpoint') from None
    with db.begin():
        user, _ = settings.context(db, principal, tenant_id)
        stored_key = None
        if body.provider_id:
            provider = settings.provider_access(db, tenant_id, user.id, body.provider_id, manage=True)
            if provider.last_test_at and provider.last_test_at.replace(tzinfo=timezone.utc) > utc_now() - DRAFT_TEST_COOLDOWN:
                raise Conflict('Please wait 10 seconds before testing again')
            provider.last_test_at = utc_now()
            if body.api_key is None:
                if base_url != provider.base_url:
                    raise ValueError('Changing API address requires a replacement Key')
                stored_key = settings.decrypt(db.get(settings.StoredKey, provider.credential_id))
            target = str(provider.id)
        else:
            if body.scope == 'tenant':
                require_membership(db, tenant_id, user.id)
                require_api_permission(db, tenant_id, user.id, 'models:manage')
            target = 'draft'
        key = body.api_key.get_secret_value() if body.api_key is not None else stored_key
        if not key:
            raise ValueError('API Key is required')
        if not body.provider_id:
            started = draft_test_started.get((tenant_id, user.id))
            if started and started.replace(tzinfo=timezone.utc) > utc_now() - DRAFT_TEST_COOLDOWN:
                raise Conflict('Please wait 10 seconds before testing again')
            draft_test_started[(tenant_id, user.id)] = utc_now()
        audit(db, tenant_id, user.id, 'provider.connection_test', 'model_provider', target, {'draft': not body.provider_id, 'model_type': model_type})
    return await check_connection(key=key, base_url=base_url, model_name=body.model_name.strip(), options={**options, 'base_url': base_url}, model_type=model_type)
