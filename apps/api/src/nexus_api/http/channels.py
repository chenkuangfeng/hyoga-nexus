"""IM channels of agents (openspec 2026-11-11-enterprise-saas E4, design section 7).

- ``/api/v1/tenants/{tenant_id}/agents/{agent_id}/channels``: list and add channels (the agent's maintainers).
- ``/api/v1/tenants/{tenant_id}/channels/{channel_id}``: stop or delete; WeChat QR binding.
- ``/api/v1/tenants/{tenant_id}/admin/channels``: overview and review queue (``enterprise_agents:manage``).

WeCom app messages arrive through the enterprise's WeCom callback (``wecom_apps.callback_event``).
The iLink login client is ``app.state.ilink_login`` when set (tests), otherwise ``ILinkLogin()``.
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal
from nexus_platform.channels import service
from nexus_platform.errors import Conflict, Forbidden, NotFound
from nexus_platform.identity.service import resolve_user

router = APIRouter(prefix='/api/v1/tenants/{tenant_id}', tags=['Channels'])


class ChannelInput(BaseModel):
    kind: Literal['wecom_app', 'wecom_bot', 'wechat', 'qq']
    name: str = Field('', max_length=80)
    wecom_app_id: UUID | None = None


class ReviewInput(BaseModel):
    approve: bool
    note: str = Field('', max_length=500)


def _login(request: Request):
    override = getattr(request.app.state, 'ilink_login', None)
    if override is not None:
        return override
    from nexus_connectors.wechat.ilink import ILinkLogin
    return ILinkLogin()


@router.get('/agents/{agent_id}/channels')
def list_channels(tenant_id: UUID, agent_id: UUID, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return {'items': service.list_agent_channels(db, principal, tenant_id, agent_id),
            'unverified_kinds': sorted(service.UNVERIFIED)}


@router.post('/agents/{agent_id}/channels', status_code=status.HTTP_201_CREATED)
def create_channel(tenant_id: UUID, agent_id: UUID, body: ChannelInput, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.create_channel(db, principal, tenant_id, agent_id, kind=body.kind, name=body.name,
                                  wecom_app_id=body.wecom_app_id)


@router.post('/channels/{channel_id}/disable')
def disable_channel(tenant_id: UUID, channel_id: UUID, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_database_session)) -> dict[str, bool]:
    service.disable_channel(db, principal, tenant_id, channel_id)
    return {'disabled': True}


@router.delete('/channels/{channel_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(tenant_id: UUID, channel_id: UUID, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> Response:
    service.disable_channel(db, principal, tenant_id, channel_id, delete=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _owned_binding_channel(db: Session, principal: Principal, tenant_id: UUID, channel_id: UUID):
    user = resolve_user(db, principal)
    row = service._channel(db, tenant_id, channel_id)
    if row.owner_user_id != user.id:
        raise NotFound('Channel not found')
    if row.kind != 'wechat' or row.status != 'binding':
        raise Conflict('The channel is not waiting for WeChat binding')
    return row


@router.post('/channels/{channel_id}/wechat/qr')
def wechat_qr(tenant_id: UUID, channel_id: UUID, request: Request, principal: Principal = Depends(get_principal),
              db: Session = Depends(get_database_session)) -> dict[str, str]:
    """Start binding: the owner scans this QR code with their own WeChat."""
    with db.begin():
        _owned_binding_channel(db, principal, tenant_id, channel_id)
    qr = asyncio.run(_login(request).fetch_qr())
    with db.begin():
        row = _owned_binding_channel(db, principal, tenant_id, channel_id)
        service.store_config(row, {'qrcode': qr['qrcode']})
    return {'qrcode_url': qr['qrcode_url']}


@router.get('/channels/{channel_id}/wechat/status')
def wechat_status(tenant_id: UUID, channel_id: UUID, request: Request, principal: Principal = Depends(get_principal),
                  db: Session = Depends(get_database_session)) -> dict[str, Any]:
    """Poll the binding once; on confirmation keep the bot token and activate the channel."""
    with db.begin():
        row = _owned_binding_channel(db, principal, tenant_id, channel_id)
        qrcode = service.channel_config(row).get('qrcode')
    if not qrcode:
        raise Conflict('Start the WeChat binding first')
    result = asyncio.run(_login(request).status(qrcode))
    if result['status'] != 'confirmed':
        return {'status': result['status']}
    if not result.get('bot_token') or not result.get('ilink_user_id'):
        raise Forbidden('WeChat did not return the bot credentials')
    with db.begin():
        view = service.complete_binding(db, tenant_id, channel_id, external_user=str(result['ilink_user_id']),
                                        credentials={'bot_token': result['bot_token'], 'base_url': result['baseurl'],
                                                     'bot_id': result.get('ilink_bot_id')})
    return {'status': 'confirmed', 'channel': view}


@router.get('/admin/channels')
def list_enterprise_channels(tenant_id: UUID, status_filter: str | None = None,
                             principal: Principal = Depends(get_principal),
                             db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return {'items': service.list_enterprise_channels(db, principal, tenant_id, status_filter)}


@router.post('/admin/channels/{channel_id}/review')
def review_channel(tenant_id: UUID, channel_id: UUID, body: ReviewInput, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.review_channel(db, principal, tenant_id, channel_id, approve=body.approve, note=body.note)
