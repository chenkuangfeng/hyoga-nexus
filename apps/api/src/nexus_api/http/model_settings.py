"""Authenticated user settings. Secrets are accepted only in write-only fields."""
from __future__ import annotations

import asyncio
from datetime import timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal, utc_now
from nexus_core.runtime import ModelRequest, ModelMessage, RuntimeFault
from nexus_platform.models import provider_settings as settings
from nexus_platform.persistence.models import ModelProfileRecord, ModelProfileVersionRecord
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.workspaces.service import audit
from nexus_runtimes.native.models.network import validate_url, provider_client
from nexus_runtimes.native.models.openai_compatible import OpenAICompatibleModel

router = APIRouter(prefix='/api/v1/workspaces/{workspace_id}/model-settings', tags=['Model settings'])


class ProviderInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=1, max_length=512)
    scope: Literal['personal', 'workspace'] = 'personal'
    api_key: SecretStr | None = None


class ModelInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class DefaultInput(BaseModel):
    scope: Literal['personal', 'workspace'] = 'personal'
    version_id: UUID | None = None


class AgentInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    instructions: str = Field(default='You are a helpful assistant.', max_length=20000)
    model_profile_version_id: UUID | None = None


def provider_values(body: ProviderInput) -> dict[str, object]:
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


@router.get('')
def list_settings(workspace_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    return settings.list_settings(db, principal, workspace_id)


@router.post('/providers', status_code=201)
def create_provider(workspace_id: UUID, body: ProviderInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    return settings.save_provider(db, principal, workspace_id, **provider_values(body))


@router.put('/providers/{provider_id}')
def update_provider(workspace_id: UUID, provider_id: UUID, body: ProviderInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    return settings.save_provider(db, principal, workspace_id, provider_id=provider_id, **provider_values(body))


@router.delete('/providers/{provider_id}')
def delete_provider(workspace_id: UUID, provider_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    settings.disable(db, principal, workspace_id, provider_id)
    return {'status': 'disabled'}


@router.post('/providers/{provider_id}/models', status_code=201)
def add_model(workspace_id: UUID, provider_id: UUID, body: ModelInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    return settings.save_model(db, principal, workspace_id, provider_id, model_name(body.name))


def model_name(value: str) -> str:
    if not value.strip():
        raise ValueError('Model name is required')
    return value.strip()


@router.put('/providers/{provider_id}/models/{profile_id}')
def edit_model(workspace_id: UUID, provider_id: UUID, profile_id: UUID, body: ModelInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    return settings.save_model(db, principal, workspace_id, provider_id, model_name(body.name), profile_id)


@router.delete('/providers/{provider_id}/models/{profile_id}')
def delete_model(workspace_id: UUID, provider_id: UUID, profile_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    settings.disable(db, principal, workspace_id, provider_id, profile_id)
    return {'status': 'disabled'}


@router.put('/default')
def set_default(workspace_id: UUID, body: DefaultInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    settings.set_default(db, principal, workspace_id, body.scope, body.version_id)
    return {'status': 'saved'}


@router.post('/agents', status_code=201)
def create_native_agent(workspace_id: UUID, body: AgentInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    from nexus_platform.agents.service import create_agent, publish_agent
    with db.begin():
        user, _ = settings.context(db, principal, workspace_id)
        selected = body.model_profile_version_id
        if selected is None:
            for scope in (str(user.id), 'workspace'):
                row = db.get(settings.Default, (workspace_id, scope))
                if row:
                    try:
                        settings.authorize_model(db, workspace_id, user.id, row.version_id)
                        selected = row.version_id
                        break
                    except NotFound:
                        continue
        if selected is None:
            raise ValueError('Select a model or configure a default first')
        settings.authorize_model(db, workspace_id, user.id, selected)
    agent = create_agent(db, principal, workspace_id, name=body.name, description='', runtime_type='native',
        instructions=body.instructions, model_profile_version_id=selected, budgets={}, bindings=[])
    version = publish_agent(db, principal, workspace_id, agent.id)
    return {'id': str(agent.id), 'published_version_id': str(version.id), 'name': agent.name}


@router.post('/providers/{provider_id}/models/{profile_id}/test')
async def test_connection(workspace_id: UUID, provider_id: UUID, profile_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_database_session)):
    with db.begin():
        user, _ = settings.context(db, principal, workspace_id)
        provider = settings.provider_access(db, workspace_id, user.id, provider_id, manage=True)
        link = db.get(settings.Link, profile_id)
        if not link or link.provider_id != provider.id or not link.active:
            raise NotFound('Model unavailable')
        if provider.last_test_at and provider.last_test_at.replace(tzinfo=timezone.utc) > utc_now() - timedelta(seconds=10):
            raise Conflict('Please wait 10 seconds before testing again')
        provider.last_test_at = utc_now()
        profile = db.get(ModelProfileRecord, profile_id)
        version = db.get(ModelProfileVersionRecord, profile.current_version_id)
        key, base_url, name = settings.decrypt(db.get(settings.StoredKey, version.credential_reference_id)), version.options['base_url'], version.model_name
        audit(db, workspace_id, user.id, 'provider.connection_test', 'model_provider', str(provider.id))
    model = None
    try:
        model = OpenAICompatibleModel(model=name, api_key=key, base_url=base_url,
                                     timeout=12, http_client=provider_client(base_url, timeout=12))
        async with asyncio.timeout(15):
            async for _ in model.stream(ModelRequest((ModelMessage('user', 'Reply OK.'),), (), 32)):
                pass
        return {'ok': True, 'message': '连接成功，流式响应正常'}
    except RuntimeFault as exc:
        return {'ok': False, 'code': exc.code, 'message': '连接未通过，请检查地址、模型名称和 Key'}
    except Exception:
        return {'ok': False, 'code': 'model_provider_unavailable', 'message': '连接未通过，请检查配置或稍后重试'}
    finally:
        key = None
        if model:
            await model.close()
