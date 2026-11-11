"""Enterprise WeCom self-built apps: admin configuration, app entry and QR sign-in, directory callbacks
(openspec 2026-11-11-enterprise-saas E3, design section 6).

- ``/api/v1/tenants/{tenant_id}/admin/wecom...``: configuration (``org:manage``).
- ``/wecom/apps/{app_id}/entry`` and ``/callback``: the app's home page inside WeCom and its OAuth callback. The
  reverse proxy must route ``/wecom/`` to the API.
- ``/api/v1/auth/wecom/qr?enterprise_code=``: QR sign-in through the enterprise's sign-in app (same callback).
- ``/api/v1/integrations/wecom/{tenant_id}/callback``: WeCom's URL check (GET) and pushed events (POST).

The WeCom client is ``app.state.wecom_api`` when set (tests), otherwise one shared ``HttpWeComApi``.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_core.platform import Principal
from nexus_platform.errors import Forbidden, NotFound, Unauthenticated
from nexus_platform.wecom import service
from nexus_platform.wecom.client import oauth_url, qr_url

admin_router = APIRouter(prefix='/api/v1/tenants/{tenant_id}/admin/wecom', tags=['WeCom'])
public_router = APIRouter(tags=['WeCom'])
_DEFAULT_API = None


def wecom_api(request: Request):
    global _DEFAULT_API
    override = getattr(request.app.state, 'wecom_api', None)
    if override is not None:
        return override
    if _DEFAULT_API is None:
        from nexus_connectors.wecom.client import HttpWeComApi
        _DEFAULT_API = HttpWeComApi()
    return _DEFAULT_API


class CorpInput(BaseModel):
    corp_id: str = Field(min_length=4, max_length=64)
    #: Callback credentials from the app's “接收消息” settings; omit to keep the stored values.
    callback_token: str | None = Field(default=None, max_length=64)
    encoding_aes_key: str | None = Field(default=None, min_length=43, max_length=43)


class AppInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    wecom_agentid: str = Field(min_length=1, max_length=32)
    secret: str = Field(min_length=1, max_length=256)
    purpose: Literal['workspace', 'admin', 'agent']
    nexus_agent_id: UUID | None = None
    qr_login: bool = False


class AppUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    secret: str | None = Field(default=None, max_length=256)
    qr_login: bool | None = None
    status: Literal['active', 'disabled'] | None = None


@admin_router.get('')
def get_config(tenant_id: UUID, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.get_config(db, principal, tenant_id)


@admin_router.put('')
def save_corp(tenant_id: UUID, body: CorpInput, principal: Principal = Depends(get_principal),
              db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.save_corp(db, principal, tenant_id, corp_id=body.corp_id, callback_token=body.callback_token,
                             encoding_aes_key=body.encoding_aes_key)


@admin_router.delete('', status_code=status.HTTP_204_NO_CONTENT)
def remove_corp(tenant_id: UUID, principal: Principal = Depends(get_principal),
                db: Session = Depends(get_database_session)) -> Response:
    service.remove_corp(db, principal, tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post('/apps', status_code=status.HTTP_201_CREATED)
def create_app(tenant_id: UUID, body: AppInput, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.create_app(db, principal, tenant_id, name=body.name, wecom_agentid=body.wecom_agentid,
                              secret=body.secret, purpose=body.purpose, nexus_agent_id=body.nexus_agent_id,
                              qr_login=body.qr_login)


@admin_router.patch('/apps/{app_id}')
def update_app(tenant_id: UUID, app_id: UUID, body: AppUpdate, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)) -> dict[str, Any]:
    return service.update_app(db, principal, tenant_id, app_id, body.model_dump(exclude_none=True))


@admin_router.delete('/apps/{app_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_app(tenant_id: UUID, app_id: UUID, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_database_session)) -> Response:
    service.delete_app(db, principal, tenant_id, app_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post('/sync', status_code=status.HTTP_202_ACCEPTED)
def request_sync(tenant_id: UUID, principal: Principal = Depends(get_principal),
                 db: Session = Depends(get_database_session)) -> dict[str, bool]:
    """Ask the worker to read the directory now (otherwise it syncs every 24 hours)."""
    service.request_sync(db, principal, tenant_id)
    return {'queued': True}


# ------------------------------------------------------------------------------------------- sign-in

def _callback_uri(request: Request, app_id: UUID) -> str:
    return str(request.url_for('wecom_app_callback', app_id=str(app_id)))


@public_router.get('/wecom/apps/{app_id}/entry')
def app_entry(app_id: UUID, request: Request, db: Session = Depends(get_database_session)):
    """The app's home page in WeCom: start silent OAuth for this app."""
    start = service.start_app_login(db, app_id)
    return RedirectResponse(oauth_url(start.corp_id, start.agentid, _callback_uri(request, app_id), start.state),
                            status_code=302)


@public_router.get('/api/v1/auth/wecom/qr')
def qr_start(request: Request, enterprise_code: str, db: Session = Depends(get_database_session)):
    """QR sign-in for the enterprise with this code, through its sign-in app."""
    app_id = service.qr_app_for(db, enterprise_code)
    start = service.start_qr_login(db, app_id)
    return RedirectResponse(qr_url(start.corp_id, start.agentid, _callback_uri(request, app_id), start.state),
                            status_code=302)


@public_router.get('/wecom/apps/{app_id}/callback', name='wecom_app_callback')
def app_callback(app_id: UUID, request: Request, code: str = '', state: str = '',
                 db: Session = Depends(get_database_session)):
    from nexus_api.http.auth import _set_session
    try:
        result = service.finish_login(db, wecom_api(request), app_id, code=code, state=state)
    except Unauthenticated:
        return RedirectResponse('/login?wecom=expired', status_code=303)
    except NotFound:
        return RedirectResponse('/login?wecom=unavailable', status_code=303)
    except Forbidden as exc:
        key = 'not_in_directory' if str(exc) == service.NOT_SYNCED else 'forbidden'
        return RedirectResponse(f'/login?wecom={key}', status_code=303)
    response = RedirectResponse(result.target, status_code=303)
    _set_session(response, result.token, result.expires)
    return response


# ------------------------------------------------------------------------------------------- callbacks

@public_router.get('/api/v1/integrations/wecom/{tenant_id}/callback')
def callback_check(tenant_id: UUID, msg_signature: str = '', timestamp: str = '', nonce: str = '',
                   echostr: str = '', db: Session = Depends(get_database_session)):
    plain = service.verify_url(db, tenant_id, msg_signature=msg_signature, timestamp=timestamp, nonce=nonce,
                               echostr=echostr)
    return PlainTextResponse(plain)


@public_router.post('/api/v1/integrations/wecom/{tenant_id}/callback')
async def callback_event(tenant_id: UUID, request: Request, msg_signature: str = '', timestamp: str = '',
                         nonce: str = '', db: Session = Depends(get_database_session)):
    body = (await request.body())[:65536].decode('utf-8', 'replace')
    message = service.decrypt_event(db, tenant_id, msg_signature=msg_signature, timestamp=timestamp, nonce=nonce,
                                    body=body)
    handler = getattr(request.app.state, 'wecom_message_handler', None)
    if message.findtext('MsgType') != 'event' and handler is not None:
        handler(db, tenant_id, message)  # application messages go to IM channels (E4)
    else:
        service.handle_contact_event(db, tenant_id, message)
    return PlainTextResponse('success')
