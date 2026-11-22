"""Authenticated user settings. Secrets are accepted only in write-only fields."""
from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
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
from nexus_runtimes.native.models.embeddings import create_embedder
from nexus_runtimes.native.models.factory import create_model
from nexus_runtimes.native.models.media import create_transcriber, create_vision
from nexus_runtimes.native.models.rerank import create_reranker

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
    display_name: str | None = Field(default=None, max_length=settings.MAX_MODEL_DISPLAY_NAME)
    options: dict[str, object] = Field(default_factory=dict)
    model_type: ModelType = 'chat'


class SharedProviderInput(ProviderInput):
    """New shared provider credentials submitted alongside its first model."""

    scope: Literal['tenant'] = 'tenant'
    api_key: SecretStr


class ModelWithProviderInput(ModelInput):
    """Combined creation request so a failed model never leaves an empty provider."""

    provider: SharedProviderInput


class EnterpriseModelEditInput(ModelInput):
    """Append a model version and optionally replace that profile's connection."""

    provider: ProviderInput


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


class CopyModelInput(BaseModel):
    """Localized suffix for the new display name, allocated by the service."""

    suffix: str = Field(default='Copy', min_length=1, max_length=32)


class ModelDebugInput(BaseModel):
    """Bounded text-only debug input for the current version of a saved model."""

    text: str = Field(min_length=1, max_length=8000)
    system_prompt: str = Field(default='', max_length=4000)
    documents: list[str] = Field(default_factory=list, max_length=16)
    max_output_tokens: int = Field(default=512, ge=1, le=2048)
    temperature: float | None = Field(default=None, ge=0, le=2)


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
    return settings.save_model(db, principal, tenant_id, provider_id, model_name(body.name),
                               model_options=body.options, model_type=body.model_type, display_name=body.display_name)


def model_name(value: str) -> str:
    """Normalize the supplier model identifier; reject empty values without invoking the supplier."""
    if not value.strip():
        raise ValueError('Model name is required')
    return value.strip()


@router.post('/admin/model-settings/models', status_code=201)
def add_model_with_provider(tenant_id: UUID, body: ModelWithProviderInput, principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)):
    """Create a new shared provider and its first model atomically."""
    provider = provider_values(body.provider)
    return settings.create_enterprise_model_with_provider(
        db, principal, tenant_id, provider_name=provider['name'], base_url=provider['base_url'],
        api_key=provider['api_key'], model_name=model_name(body.name), model_type=body.model_type,
        model_options=body.options, display_name=body.display_name,
    )


@tenant_admin_route(router, '/model-settings/providers/{provider_id}/models/{profile_id}', methods=['PUT'])
def edit_model(tenant_id: UUID, provider_id: UUID, profile_id: UUID, body: ModelInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Append a model version; preserve already published AgentVersion references."""
    return settings.save_model(db, principal, tenant_id, provider_id, model_name(body.name), profile_id,
                               model_options=body.options, model_type=body.model_type, display_name=body.display_name)


@router.put('/admin/model-settings/providers/{provider_id}/models/{profile_id}/configuration')
def edit_model_with_provider(tenant_id: UUID, provider_id: UUID, profile_id: UUID, body: EnterpriseModelEditInput,
                             principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Save a model and its per-profile connection within a single transaction."""
    provider = provider_values(body.provider)
    if provider['scope'] != 'tenant':
        raise ValueError('Enterprise models require a shared scope')
    connection = settings.ModelConnectionEdit(provider['name'], provider['base_url'], provider['api_key'])
    return settings.save_model(db, principal, tenant_id, provider_id, model_name(body.name), profile_id,
                               model_options=body.options, model_type=body.model_type,
                               display_name=body.display_name, connection=connection)


@router.post('/admin/model-settings/providers/{provider_id}/models/{profile_id}/copy', status_code=201)
def copy_model(tenant_id: UUID, provider_id: UUID, profile_id: UUID, body: CopyModelInput,
               principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Copy the current version of an enterprise model into an independent profile."""
    suffix = body.suffix.strip()
    if not suffix or not suffix.isprintable():
        raise ValueError('Invalid model copy suffix')
    return settings.copy_enterprise_model(db, principal, tenant_id, provider_id, profile_id, ' ' + suffix)


@tenant_admin_route(router, '/model-settings/providers/{provider_id}/models/{profile_id}', methods=['DELETE'])
def delete_model(tenant_id: UUID, provider_id: UUID, profile_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Disable this model and clear its defaults without deleting historical runs."""
    settings.disable(db, principal, tenant_id, provider_id, profile_id)
    return {'status': 'disabled'}


@router.delete('/admin/model-settings/providers/{provider_id}/models/{profile_id}/configuration')
def delete_model_configuration(tenant_id: UUID, provider_id: UUID, profile_id: UUID,
                               principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Remove a model from the enterprise catalog after checking active references."""
    settings.disable(db, principal, tenant_id, provider_id, profile_id, protect_references=True)
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


UNSUPPORTED_TYPE_MESSAGE = '该模型类型暂不支持连接测试'
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
    """Run one bounded request using the configured protocol and return a sanitized result.

    Responses carry no generated text, vectors, scores or raw supplier errors.
    """
    if model_type not in ('chat', 'embedding', 'rerank'):
        return {'ok': False, 'code': 'unsupported_for_type', 'message': UNSUPPORTED_TYPE_MESSAGE}
    model = None
    try:
        options = {'protocol': 'openai_chat_completions', **options, 'base_url': base_url}
        if model_type == 'embedding':
            model = create_embedder(model=model_name, api_key=key, options=options, timeout=12)
            async with asyncio.timeout(15):
                vectors = await model.embed(['ping'])
            if len(vectors) != 1 or not vectors[0] or not all(math.isfinite(value) for value in vectors[0]):
                raise RuntimeFault('model_stream_invalid')
            return {'ok': True, 'message': '连接成功，向量化响应正常'}
        if model_type == 'rerank':
            model = create_reranker(model=model_name, api_key=key, options=options, timeout=12)
            async with asyncio.timeout(15):
                scores = await model.rerank('ping', ['ping'])
            if len(scores) != 1 or scores[0][0] != 0 or not math.isfinite(scores[0][1]):
                raise RuntimeFault('model_stream_invalid')
            return {'ok': True, 'message': '连接成功，重排响应正常'}
        if options['protocol'] == 'openai_chat_completions':
            model = OpenAICompatibleModel(model=model_name, api_key=key, base_url=base_url,
                                         timeout=12, http_client=provider_client(base_url, timeout=12), options=options)
        else:
            model = create_model(model=model_name, api_key=key, options=options, timeout=12)
        async with asyncio.timeout(15):
            async for _ in model.stream(ModelRequest((ModelMessage('user', 'Reply OK.'),), (), 32)):
                pass
        return {'ok': True, 'message': '连接成功，流式响应正常'}
    except RuntimeFault as exc:
        return {'ok': False, 'code': exc.code, 'message': CONNECTION_FAILURE_MESSAGES.get(exc.code, DEFAULT_FAILURE_MESSAGE)}
    except TimeoutError:
        return {'ok': False, 'code': 'model_timeout', 'message': CONNECTION_FAILURE_MESSAGES['model_timeout']}
    except Exception:
        return {'ok': False, 'code': 'model_provider_unavailable', 'message': '连接未通过，请检查配置或稍后重试'}
    finally:
        if model:
            await model.close()


def saved_probe(db: Session, principal: Principal, tenant_id: UUID, provider_id: UUID, profile_id: UUID,
                *, debug_types: tuple[str, ...] = ()) -> tuple[str, str, dict, str]:
    """Snapshot the authorized current model and reserve a per-provider probe slot."""
    with db.begin():
        user, _ = settings.context(db, principal, tenant_id)
        provider = settings.provider_access(db, tenant_id, user.id, provider_id, manage=True)
        if debug_types and provider.owner_user_id is not None:
            raise NotFound('Provider unavailable')
        link = db.get(settings.Link, profile_id)
        if not link or link.provider_id != provider.id or not link.active:
            raise NotFound('Model unavailable')
        profile = db.get(ModelProfileRecord, profile_id)
        if debug_types and profile.model_type not in debug_types:
            raise ValueError(UNSUPPORTED_TYPE_MESSAGE)
        if provider.last_test_at and provider.last_test_at.replace(tzinfo=timezone.utc) > utc_now() - DRAFT_TEST_COOLDOWN:
            raise Conflict('Please wait 10 seconds before testing again')
        provider.last_test_at = utc_now()
        version = db.get(ModelProfileVersionRecord, profile.current_version_id)
        key = settings.decrypt(db.get(settings.StoredKey, version.credential_reference_id))
        audit(db, tenant_id, user.id, 'provider.model_debug' if debug_types else 'provider.connection_test',
              'model_provider', str(provider.id))
        return key, version.model_name, dict(version.options), profile.model_type


@tenant_admin_route(router, '/model-settings/providers/{provider_id}/models/{profile_id}/test', methods=['POST'])
async def test_connection(tenant_id: UUID, provider_id: UUID, profile_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Test an authorized saved model with a bounded minimal request."""
    key, name, options, model_type = saved_probe(db, principal, tenant_id, provider_id, profile_id)
    return await check_connection(key=key, base_url=options['base_url'], model_name=name, options=options, model_type=model_type)


async def run_model_debug(key: str, name: str, options: dict, model_type: str, body: ModelDebugInput) -> dict[str, object]:
    """Execute a text-only debug request and return a bounded, typed result."""
    arguments = {'model': name, 'api_key': key, 'options': options, 'timeout': 12}
    if model_type == 'embedding':
        adapter = create_embedder(**arguments)
    elif model_type == 'rerank':
        adapter = create_reranker(**arguments)
    else:
        if body.temperature is not None:
            options['temperature'] = body.temperature
        options.pop('text_tools', None)
        adapter = create_model(**arguments)
    try:
        async with asyncio.timeout(15):
            if model_type == 'embedding':
                vectors = await adapter.embed([body.text])
                if len(vectors) != 1 or not vectors[0] or not all(math.isfinite(value) for value in vectors[0]):
                    raise RuntimeFault('model_stream_invalid')
                return {'type': 'embedding', 'dimension': len(vectors[0]), 'preview': vectors[0][:16]}
            if model_type == 'rerank':
                scores = await adapter.rerank(body.text, body.documents)
                if (sorted(index for index, _ in scores) != list(range(len(body.documents)))
                        or not all(math.isfinite(score) for _, score in scores)):
                    raise RuntimeFault('model_stream_invalid')
                return {'type': 'rerank', 'scores': [
                    {'index': index, 'score': score} for index, score in sorted(scores, key=lambda item: -item[1])
                ]}
            messages = []
            if body.system_prompt:
                messages.append(ModelMessage('system', body.system_prompt))
            messages.append(ModelMessage('user', body.text))
            request = ModelRequest(tuple(messages), (), body.max_output_tokens)
            chunks = []
            async for chunk in adapter.stream(request):
                if chunk.kind == 'text':
                    chunks.append(chunk.text)
                elif chunk.kind == 'done' and chunk.finish_reason == 'content_filter':
                    raise RuntimeFault('model_response_failed')
            return {'type': 'chat', 'text': ''.join(chunks).replace(key, '[redacted]')}
    finally:
        await adapter.close()


@router.post('/admin/model-settings/providers/{provider_id}/models/{profile_id}/debug')
async def debug_model(tenant_id: UUID, provider_id: UUID, profile_id: UUID, body: ModelDebugInput,
                      principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Debug a shared model using its saved credentials without logging input or output."""
    if any(not document.strip() or len(document) > 2000 for document in body.documents) or not body.text.strip():
        raise ValueError('Invalid model debug input')
    key, name, options, model_type = saved_probe(db, principal, tenant_id, provider_id, profile_id,
                                               debug_types=('chat', 'embedding', 'rerank'))
    if model_type == 'rerank' and not body.documents:
        raise ValueError('At least one candidate document is required')
    return await debug_reply(run_model_debug(key, name, options, model_type, body))


async def debug_reply(operation: Awaitable[dict[str, object]]) -> dict[str, object]:
    """Translate provider failures without exposing their response bodies."""
    try:
        return {'ok': True, 'result': await operation}
    except RuntimeFault as exc:
        return {'ok': False, 'message': CONNECTION_FAILURE_MESSAGES.get(exc.code, DEFAULT_FAILURE_MESSAGE)}
    except TimeoutError:
        return {'ok': False, 'message': CONNECTION_FAILURE_MESSAGES['model_timeout']}
    except Exception:
        return {'ok': False, 'message': DEFAULT_FAILURE_MESSAGE}


DEBUG_MEDIA_LIMIT = 10 * 1024 * 1024
DEBUG_IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
DEBUG_AUDIO_EXTENSIONS = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.webm'}


async def run_media_debug(key: str, name: str, options: dict, model_type: str, data: bytes,
                          extension: str, prompt: str) -> dict[str, object]:
    """Feed the selected file to the existing vision or transcription adapter."""
    arguments = {'model': name, 'api_key': key, 'options': options, 'timeout': 25}
    if model_type == 'vision':
        adapter = create_vision(**arguments)
    else:
        adapter = create_transcriber(**arguments)
    try:
        async with asyncio.timeout(30):
            if model_type == 'vision':
                text = await adapter.describe(data, DEBUG_IMAGE_TYPES[extension], '', prompt, max_tokens=512)
            else:
                text = await adapter.transcribe(data, 'sample' + extension)
            return {'type': model_type, 'text': text.replace(key, '[redacted]')[:16384]}
    finally:
        await adapter.close()


@router.post('/admin/model-settings/providers/{provider_id}/models/{profile_id}/debug-media')
async def debug_model_media(tenant_id: UUID, provider_id: UUID, profile_id: UUID, file: UploadFile = File(...),
                            text: str = Form(default='', max_length=8000), principal: Principal = Depends(get_principal),
                            db: Session = Depends(get_database_session)):
    """Run one bounded image or audio sample without retaining the upload."""
    data = await file.read(DEBUG_MEDIA_LIMIT + 1)
    if not data or len(data) > DEBUG_MEDIA_LIMIT:
        raise ValueError('Debug file must be between 1 byte and 10 MiB')
    extension = PurePath(file.filename or '').suffix.lower()
    key, name, options, model_type = saved_probe(db, principal, tenant_id, provider_id, profile_id,
                                               debug_types=('vision', 'speech'))
    extensions = DEBUG_IMAGE_TYPES if model_type == 'vision' else DEBUG_AUDIO_EXTENSIONS
    if extension not in extensions:
        raise ValueError('Unsupported model debug file type')
    return await debug_reply(run_media_debug(key, name, options, model_type, data, extension, text))


@tenant_admin_route(router, '/model-settings/test', methods=['POST'])
async def test_draft(tenant_id: UUID, body: DraftTestInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    """Test the configuration currently in the form, before anything is saved.

    Authorization matches saving: an edit needs management of the existing provider; a new
    shared provider needs `models:manage`. Errors never echo the Key, the address or supplier text."""
    options = settings.validate_model_options(dict(body.options))
    model_type = settings.validate_model_type(body.model_type)
    name = model_name(body.model_name)
    try:
        base_url = validate_url(body.base_url)
    except RuntimeFault:
        raise ValueError('API address is not permitted; use a public HTTPS endpoint') from None
    with db.begin():
        user, _ = settings.context(db, principal, tenant_id)
        stored_key = None
        if body.provider_id:
            provider = settings.provider_access(db, tenant_id, user.id, body.provider_id, manage=True)
            if body.scope != ('personal' if provider.owner_user_id else 'tenant'):
                raise NotFound('Provider unavailable')
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
    return await check_connection(key=key, base_url=base_url, model_name=name, options=options, model_type=model_type)
