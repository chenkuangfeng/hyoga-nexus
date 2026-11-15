"""WeCom self-built apps of an enterprise: configuration, sign-in, directory sync and callbacks
(openspec 2026-11-11-enterprise-saas E3, decision 5; design section 6).

Configuration (needs ``org:manage``): one corp per enterprise, any number of apps with a purpose (``workspace``,
``admin``, ``agent``). Secrets are sealed with the deployment key, bound to the row id, and never returned.

Sign-in: every app has an entry path ``/wecom/apps/{app_id}/entry``. Inside WeCom it starts silent OAuth; the QR
flow uses the app marked ``qr_login``. The callback resolves the member ``userid``; a known identity signs in, a
member already read from the directory gets an account (role ``contributor``, membership source ``wecom``) on first
entry, anyone else is refused. The purpose decides where the client lands; permissions are still checked there.

Directory sync uses the QR app's secret (or the first workspace app's): departments become ``org_units`` with
``source = 'wecom'``, members are kept in ``wecom_members``. A member who left (deleted, or out of the visible range)
loses the enterprise membership, unless they are an owner. Assets stay where they are (decision 8).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.auth.sessions import issue_session
from nexus_platform.auth.wecom import WECOM_PROVIDER, _consume_state, _issue_state
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import require_api_permission
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.models.provider_settings import cipher
from nexus_platform.persistence.models import (AgentRecord, MembershipRecord, OrgUnitRecord, TenantRecord,
                                               UserIdentityRecord, UserOrgUnitRecord, UserRecord, WeComAppRecord,
                                               WeComCorpRecord, WeComMemberRecord)
from nexus_platform.wecom.client import WeComApi, WeComError
from nexus_platform.wecom.crypto import CallbackCrypto, CallbackError

PURPOSES = ('workspace', 'admin', 'agent')
STATE_APP, STATE_QR = 'wecom_app', 'wecom_qr'
SYNC_INTERVAL = timedelta(hours=24)
NOT_SYNCED = '你还不在企业通讯录中，请联系企业管理员把你加入应用的可见范围'
_PREFIX = 'sealed:v1:'
_ENCRYPT = re.compile(r'<Encrypt><!\[CDATA\[([A-Za-z0-9+/=]+)\]\]></Encrypt>')


# ---------------------------------------------------------------------------------------------- secrets

def _seal(row_id: UUID, value: str) -> str:
    return _PREFIX + cipher().encrypt(f'{row_id}\n{value}'.encode()).decode()


def _open(row_id: UUID, token: str | None) -> str:
    if not token:
        return ''
    identity, value = cipher().decrypt(token[len(_PREFIX):].encode()).decode().split('\n', 1)
    if identity != str(row_id):
        raise InvalidConfiguration('Sealed WeCom secret belongs to another record')
    return value


# ---------------------------------------------------------------------------------------------- configuration

def _manager(db: Session, principal: Principal, tenant_id: UUID) -> UserRecord:
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    require_api_permission(db, tenant_id, user.id, 'org:manage')
    return user


def entry_path(app: WeComAppRecord) -> str:
    return f'/wecom/apps/{app.id}/entry'


def app_view(app: WeComAppRecord) -> dict[str, Any]:
    return {'id': str(app.id), 'name': app.name, 'wecom_agentid': app.wecom_agentid, 'purpose': app.purpose,
            'nexus_agent_id': str(app.nexus_agent_id) if app.nexus_agent_id else None, 'qr_login': app.qr_login,
            'status': app.status, 'entry_path': entry_path(app), 'created_at': app.created_at.isoformat()}


def config_view(db: Session, corp: WeComCorpRecord | None) -> dict[str, Any]:
    if corp is None:
        return {'configured': False, 'apps': []}
    apps = db.scalars(select(WeComAppRecord).where(WeComAppRecord.tenant_id == corp.tenant_id)
                      .order_by(WeComAppRecord.created_at)).all()
    return {'configured': True, 'corp_id': corp.corp_id,
            'callback_configured': bool(corp.callback_token_ciphertext and corp.encoding_aes_key_ciphertext),
            'callback_path': f'/api/v1/integrations/wecom/{corp.tenant_id}/callback',
            'sync_status': corp.sync_status, 'sync_error': corp.sync_error,
            'synced_at': corp.synced_at.isoformat() if corp.synced_at else None,
            'apps': [app_view(app) for app in apps]}


def get_config(db: Session, principal: Principal, tenant_id: UUID) -> dict[str, Any]:
    with db.begin():
        _manager(db, principal, tenant_id)
        return config_view(db, db.get(WeComCorpRecord, tenant_id))


def save_corp(db: Session, principal: Principal, tenant_id: UUID, *, corp_id: str,
              callback_token: str | None = None, encoding_aes_key: str | None = None) -> dict[str, Any]:
    """Bind the enterprise to a WeCom corp; callback credentials are replaced only when given."""
    corp_id = (corp_id or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{4,64}', corp_id):
        raise InvalidConfiguration('corp_id is invalid')
    if encoding_aes_key is not None and encoding_aes_key and len(encoding_aes_key) != 43:
        raise InvalidConfiguration('EncodingAESKey must have 43 characters')
    with db.begin():
        user = _manager(db, principal, tenant_id)
        other = db.scalar(select(WeComCorpRecord.tenant_id).where(WeComCorpRecord.corp_id == corp_id))
        if other is not None and other != tenant_id:
            raise Conflict('This WeCom corp is already bound to another enterprise')
        corp = db.get(WeComCorpRecord, tenant_id)
        if corp is None:
            corp = WeComCorpRecord(tenant_id=tenant_id, corp_id=corp_id, sync_status='never', updated_at=utc_now())
            db.add(corp)
        elif corp.corp_id != corp_id:
            raise Conflict('The corp of an enterprise cannot change; remove the WeCom configuration first')
        if callback_token:
            corp.callback_token_ciphertext = _seal(tenant_id, callback_token)
        if encoding_aes_key:
            corp.encoding_aes_key_ciphertext = _seal(tenant_id, encoding_aes_key)
        corp.updated_by, corp.updated_at = user.id, utc_now()
        db.flush()
        tenant = db.get(TenantRecord, tenant_id)
        tenant.wecom_corp_id = corp_id
        audit(db, tenant_id, user.id, 'wecom.corp_saved', 'tenant', str(tenant_id), {'corp_id': corp_id})
        return config_view(db, corp)


def remove_corp(db: Session, principal: Principal, tenant_id: UUID) -> None:
    with db.begin():
        user = _manager(db, principal, tenant_id)
        corp = db.get(WeComCorpRecord, tenant_id)
        if corp is None:
            raise NotFound('WeCom is not configured')
        db.query(WeComAppRecord).filter(WeComAppRecord.tenant_id == tenant_id).delete()
        db.delete(corp)
        db.get(TenantRecord, tenant_id).wecom_corp_id = None
        audit(db, tenant_id, user.id, 'wecom.corp_removed', 'tenant', str(tenant_id), {})


def _check_agent(db: Session, tenant_id: UUID, purpose: str, agent_id: UUID | None) -> None:
    if purpose not in PURPOSES:
        raise InvalidConfiguration('purpose must be workspace, admin or agent')
    if (purpose == 'agent') != (agent_id is not None):
        raise InvalidConfiguration('An agent app names exactly one agent; other apps name none')
    if agent_id is not None:
        agent = db.get(AgentRecord, agent_id)
        if agent is None or agent.tenant_id != tenant_id or agent.status == 'archived':
            raise NotFound('Agent not found')
        taken = db.scalar(select(WeComAppRecord.id).where(WeComAppRecord.nexus_agent_id == agent_id))
        if taken is not None:
            raise Conflict('This agent already has a WeCom app')


def _clear_qr(db: Session, tenant_id: UUID, keep: UUID) -> None:
    for app in db.scalars(select(WeComAppRecord).where(WeComAppRecord.tenant_id == tenant_id,
                                                        WeComAppRecord.qr_login.is_(True), WeComAppRecord.id != keep)):
        app.qr_login = False
    db.flush()


def create_app(db: Session, principal: Principal, tenant_id: UUID, *, name: str, wecom_agentid: str, secret: str,
               purpose: str, nexus_agent_id: UUID | None = None, qr_login: bool = False) -> dict[str, Any]:
    name, wecom_agentid = (name or '').strip()[:80], (wecom_agentid or '').strip()
    if not name or not re.fullmatch(r'[0-9]{1,32}', wecom_agentid) or not secret:
        raise InvalidConfiguration('name, a numeric AgentId and the app secret are required')
    with db.begin():
        user = _manager(db, principal, tenant_id)
        if db.get(WeComCorpRecord, tenant_id) is None:
            raise InvalidConfiguration('Bind the enterprise to a WeCom corp first')
        _check_agent(db, tenant_id, purpose, nexus_agent_id)
        if db.scalar(select(WeComAppRecord.id).where(WeComAppRecord.tenant_id == tenant_id,
                                                     WeComAppRecord.wecom_agentid == wecom_agentid)):
            raise Conflict('This AgentId is already registered')
        now, app_id = utc_now(), new_id()
        if qr_login:
            _clear_qr(db, tenant_id, app_id)
        app = WeComAppRecord(id=app_id, tenant_id=tenant_id, name=name, wecom_agentid=wecom_agentid,
                             secret_ciphertext=_seal(app_id, secret), purpose=purpose, nexus_agent_id=nexus_agent_id,
                             qr_login=bool(qr_login), status='active', created_by=user.id, created_at=now,
                             updated_at=now)
        db.add(app)
        db.flush()
        audit(db, tenant_id, user.id, 'wecom.app_created', 'wecom_app', str(app.id),
              {'purpose': purpose, 'wecom_agentid': wecom_agentid})
        return app_view(app)


def update_app(db: Session, principal: Principal, tenant_id: UUID, app_id: UUID, changes: dict[str, Any]
               ) -> dict[str, Any]:
    with db.begin():
        user = _manager(db, principal, tenant_id)
        app = db.get(WeComAppRecord, app_id)
        if app is None or app.tenant_id != tenant_id:
            raise NotFound('WeCom app not found')
        if changes.get('name'):
            app.name = str(changes['name']).strip()[:80]
        if changes.get('secret'):
            app.secret_ciphertext = _seal(app.id, str(changes['secret']))
        if 'status' in changes:
            if changes['status'] not in ('active', 'disabled'):
                raise InvalidConfiguration('status must be active or disabled')
            app.status = changes['status']
        if 'qr_login' in changes:
            if changes['qr_login']:
                _clear_qr(db, tenant_id, app.id)
            app.qr_login = bool(changes['qr_login'])
        app.updated_at = utc_now()
        audit(db, tenant_id, user.id, 'wecom.app_updated', 'wecom_app', str(app.id), {'fields': sorted(changes)})
        return app_view(app)


def delete_app(db: Session, principal: Principal, tenant_id: UUID, app_id: UUID) -> None:
    with db.begin():
        user = _manager(db, principal, tenant_id)
        app = db.get(WeComAppRecord, app_id)
        if app is None or app.tenant_id != tenant_id:
            raise NotFound('WeCom app not found')
        db.delete(app)
        audit(db, tenant_id, user.id, 'wecom.app_deleted', 'wecom_app', str(app_id), {})


# ---------------------------------------------------------------------------------------------- sign-in

@dataclass(frozen=True)
class LoginStart:
    corp_id: str
    agentid: str
    state: str


@dataclass(frozen=True)
class LoginResult:
    token: str
    expires: object
    user_id: UUID
    tenant_id: UUID
    target: str


def _live_app(db: Session, app_id: UUID) -> tuple[WeComAppRecord, WeComCorpRecord]:
    app = db.get(WeComAppRecord, app_id)
    corp = db.get(WeComCorpRecord, app.tenant_id) if app is not None else None
    tenant = db.get(TenantRecord, app.tenant_id) if app is not None else None
    if app is None or corp is None or app.status != 'active' or tenant is None or tenant.status != 'active':
        raise NotFound('WeCom app not found')
    return app, corp


def start_app_login(db: Session, app_id: UUID) -> LoginStart:
    """State and app identifiers for silent sign-in inside WeCom."""
    with db.begin():
        app, corp = _live_app(db, app_id)
        corp_id, agentid = corp.corp_id, app.wecom_agentid
    return LoginStart(corp_id, agentid, _issue_state(db, STATE_APP, None))


def qr_app_for(db: Session, enterprise_code: str) -> UUID:
    """The app used for QR sign-in of the enterprise with this code."""
    with db.begin():
        tenant = db.scalar(select(TenantRecord).where(TenantRecord.code == (enterprise_code or '').strip().lower()))
        if tenant is None:
            raise NotFound('Enterprise not found')
        app = _sign_in_app(db, tenant.id)
        if app is None:
            raise NotFound('This enterprise has not enabled WeCom sign-in')
        return app.id


def _sign_in_app(db: Session, tenant_id: UUID) -> WeComAppRecord | None:
    apps = db.scalars(select(WeComAppRecord).where(WeComAppRecord.tenant_id == tenant_id,
                                                   WeComAppRecord.status == 'active')
                      .order_by(WeComAppRecord.created_at)).all()
    return (next((app for app in apps if app.qr_login), None)
            or next((app for app in apps if app.purpose == 'workspace'), None)
            or (apps[0] if apps else None))


def start_qr_login(db: Session, app_id: UUID) -> LoginStart:
    with db.begin():
        app, corp = _live_app(db, app_id)
        corp_id, agentid = corp.corp_id, app.wecom_agentid
    return LoginStart(corp_id, agentid, _issue_state(db, STATE_QR, None))


def _target(app: WeComAppRecord, qr: bool) -> str:
    if qr or app.purpose == 'workspace':
        return '/'
    if app.purpose == 'admin':
        return '/admin/'
    return f'/agents/{app.nexus_agent_id}/chat'


def _ensure_membership(db: Session, tenant_id: UUID, user_id: UUID, member: WeComMemberRecord | None) -> None:
    membership = db.get(MembershipRecord, (tenant_id, user_id))
    if membership is not None and membership.status == 'active':
        return
    if membership is not None and membership.status == 'suspended':
        raise Forbidden('Enterprise membership is suspended')
    if member is None or not member.active:
        raise Forbidden(NOT_SYNCED)
    if membership is None:
        db.add(MembershipRecord(tenant_id=tenant_id, user_id=user_id, role='contributor', status='active',
                                joined_at=utc_now(), source='wecom'))
    else:
        membership.status, membership.revoked_at = 'active', None
    db.flush()


def finish_login(db: Session, api: WeComApi, app_id: UUID, *, code: str, state: str) -> LoginResult:
    """Exchange the code, sign the member in (creating the account on first entry) and pick the landing path."""
    purpose = _state_purpose(db, state)
    with db.begin():
        _consume_state(db, state, purpose)
        app, corp = _live_app(db, app_id)
        corp_id, secret, tenant_id = corp.corp_id, _open(app.id, app.secret_ciphertext), app.tenant_id
    try:
        userid = api.get_userid(corp_id, secret, code)
    except WeComError as exc:
        raise Forbidden('企业微信授权未通过，请重新进入') from exc
    with db.begin():
        app, _ = _live_app(db, app_id)
        member = db.get(WeComMemberRecord, (tenant_id, userid))
        identity = db.scalar(select(UserIdentityRecord).where(
            UserIdentityRecord.provider == WECOM_PROVIDER, UserIdentityRecord.scope == corp_id,
            UserIdentityRecord.external_id == userid))
        if identity is None:
            if member is None or not member.active:
                raise Forbidden(NOT_SYNCED)
            now = utc_now()
            user = UserRecord(id=new_id(), display_name=(member.name or userid)[:160], email=None, status='active',
                              must_change_password=False, created_at=now)
            db.add(user)
            db.flush()
            identity = UserIdentityRecord(id=new_id(), user_id=user.id, provider=WECOM_PROVIDER, scope=corp_id,
                                          external_id=userid, verified_at=now, created_at=now)
            db.add(identity)
            db.flush()
            _ensure_membership(db, tenant_id, user.id, member)
            audit(db, tenant_id, user.id, 'wecom.account_created', 'user', str(user.id), {'userid': userid})
        user = db.get(UserRecord, identity.user_id)
        if user is None or user.status != 'active':
            raise Forbidden('The account is disabled')
        _ensure_membership(db, tenant_id, user.id, member)
        if member is not None and member.user_id is None:
            member.user_id = user.id
            _place_member(db, tenant_id, user.id, member.department_ids)
        user.preferences = {**(user.preferences or {}), 'last_active_tenant_id': str(tenant_id)}
        token, expires = issue_session(db, user.id, identity.id)
        audit(db, tenant_id, user.id, 'wecom.signed_in', 'wecom_app', str(app.id), {'qr': purpose == STATE_QR})
        return LoginResult(token, expires, user.id, tenant_id, _target(app, purpose == STATE_QR))


def _state_purpose(db: Session, raw: str) -> str:
    from nexus_platform.auth.wecom import state_purpose
    purpose = state_purpose(db, raw)
    if purpose not in (STATE_APP, STATE_QR):
        from nexus_platform.errors import Unauthenticated
        raise Unauthenticated('登录已失效，请重新发起')
    return purpose


# ---------------------------------------------------------------------------------------------- directory sync

def _sync_secret(db: Session, tenant_id: UUID) -> tuple[WeComCorpRecord, str]:
    corp = db.get(WeComCorpRecord, tenant_id)
    if corp is None:
        raise NotFound('WeCom is not configured')
    app = _sign_in_app(db, tenant_id)
    if app is None:
        raise InvalidConfiguration('Register a WeCom app before syncing the directory')
    return corp, _open(app.id, app.secret_ciphertext)


def _unique_name(db: Session, parent_id: UUID | None, name: str, own_id: UUID | None) -> str:
    candidate, number = name[:150] or '未命名部门', 1
    while db.scalar(select(OrgUnitRecord.id).where(OrgUnitRecord.parent_id == parent_id,
                                                   OrgUnitRecord.name == candidate,
                                                   OrgUnitRecord.id != own_id) if own_id else
                    select(OrgUnitRecord.id).where(OrgUnitRecord.parent_id == parent_id,
                                                   OrgUnitRecord.name == candidate)) is not None:
        number += 1
        candidate = f'{name[:140]} ({number})'
    return candidate


def _apply_departments(db: Session, tenant_id: UUID, departments: list[dict]) -> dict[str, UUID]:
    """Mirror the departments into the enterprise tree; return WeCom id -> unit id."""
    now = utc_now()
    by_id = {str(item['id']): item for item in departments}
    root = db.scalar(select(OrgUnitRecord).where(OrgUnitRecord.tenant_id == tenant_id,
                                                 OrgUnitRecord.parent_id.is_(None)))
    tops = [key for key, item in by_id.items() if str(item.get('parentid', '0')) not in by_id]
    if root is None:
        name = by_id[tops[0]].get('name') if len(tops) == 1 else None
        tenant = db.get(TenantRecord, tenant_id)
        root_id = new_id()
        root = OrgUnitRecord(id=root_id, tenant_id=tenant_id, root_id=root_id, parent_id=None,
                             name=(name or tenant.name)[:160], status='active', source='wecom',
                             external_id=tops[0] if len(tops) == 1 else None, created_at=now, updated_at=now)
        db.add(root)
        db.flush()
    elif len(tops) == 1 and root.external_id is None and not db.scalar(select(OrgUnitRecord.id).where(
            OrgUnitRecord.tenant_id == tenant_id, OrgUnitRecord.external_id == tops[0])):
        root.external_id = tops[0]  # the enterprise root stands for WeCom's top department
    mapping: dict[str, UUID] = {}
    if root.external_id:
        mapping[root.external_id] = root.id

    def depth(key: str) -> int:
        level, seen = 0, set()
        while key in by_id and key not in seen:
            seen.add(key)
            key = str(by_id[key].get('parentid', '0'))
            level += 1
        return level

    for key in sorted(by_id, key=depth):
        if key in mapping:
            continue
        item = by_id[key]
        parent_id = mapping.get(str(item.get('parentid', '0')), root.id)
        unit = db.scalar(select(OrgUnitRecord).where(OrgUnitRecord.tenant_id == tenant_id,
                                                     OrgUnitRecord.external_id == key))
        name = str(item.get('name') or key)
        if unit is None:
            unit_id = new_id()
            unit = OrgUnitRecord(id=unit_id, tenant_id=tenant_id, root_id=root.id, parent_id=parent_id,
                                 name=_unique_name(db, parent_id, name, None), status='active', source='wecom',
                                 external_id=key, created_at=now, updated_at=now)
            db.add(unit)
        else:
            if unit.parent_id != parent_id or not unit.name.startswith(name[:140]):
                unit.parent_id, unit.name = parent_id, _unique_name(db, parent_id, name, unit.id)
            unit.status, unit.updated_at = 'active', now
        db.flush()
        mapping[key] = unit.id
    for unit in db.scalars(select(OrgUnitRecord).where(OrgUnitRecord.tenant_id == tenant_id,
                                                       OrgUnitRecord.source == 'wecom',
                                                       OrgUnitRecord.status == 'active')):
        if unit.external_id not in mapping and unit.id != root.id:
            unit.status, unit.updated_at = 'disabled', now
    return mapping


def _place_member(db: Session, tenant_id: UUID, user_id: UUID, department_ids: list) -> None:
    """Keep the member's WeCom-sourced positions equal to the directory; manual positions are untouched."""
    units = {unit.external_id: unit for unit in db.scalars(select(OrgUnitRecord).where(
        OrgUnitRecord.tenant_id == tenant_id, OrgUnitRecord.external_id.is_not(None)))}
    wanted = [units[str(dept)].id for dept in department_ids if str(dept) in units]
    current = db.scalars(select(UserOrgUnitRecord).where(UserOrgUnitRecord.tenant_id == tenant_id,
                                                         UserOrgUnitRecord.user_id == user_id)).all()
    wecom_units = {unit.id for unit in units.values() if unit.source == 'wecom' or unit.external_id}
    for row in current:
        if row.unit_id in wecom_units and row.unit_id not in wanted:
            db.delete(row)
    db.flush()
    present = {row.unit_id for row in db.scalars(select(UserOrgUnitRecord).where(
        UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == user_id))}
    has_primary = db.scalar(select(UserOrgUnitRecord.unit_id).where(
        UserOrgUnitRecord.tenant_id == tenant_id, UserOrgUnitRecord.user_id == user_id,
        UserOrgUnitRecord.is_primary.is_(True))) is not None
    for unit_id in wanted:
        if unit_id not in present:
            db.add(UserOrgUnitRecord(tenant_id=tenant_id, user_id=user_id, unit_id=unit_id,
                                     is_primary=not has_primary, created_at=utc_now()))
            has_primary = True
    db.flush()


def _system_actor(db: Session, tenant_id: UUID) -> UUID:
    """Audit rows need an actor; changes made by the WeCom directory are recorded against the enterprise's creator
    with ``by = 'wecom'`` in the metadata."""
    return db.get(TenantRecord, tenant_id).created_by


def revoke_member(db: Session, tenant_id: UUID, member: WeComMemberRecord, reason: str) -> bool:
    """A member left: mark them inactive and revoke the enterprise membership (owners are kept)."""
    member.active = False
    if member.user_id is None:
        return False
    membership = db.get(MembershipRecord, (tenant_id, member.user_id))
    if membership is None or membership.status not in {'active', 'suspended'} or membership.role == 'owner':
        return False
    membership.status, membership.revoked_at = 'revoked', utc_now()
    membership.suspended_at = None
    audit(db, tenant_id, _system_actor(db, tenant_id), 'wecom.member_left', 'user', str(member.user_id),
          {'userid': member.userid, 'reason': reason, 'by': 'wecom'})
    return True


def sync_directory(db: Session, api: WeComApi, tenant_id: UUID) -> dict[str, int]:
    """Read departments and members through the sign-in app and mirror them. Network calls run outside a
    transaction; failures are recorded on the corp and re-raised as WeComError."""
    with db.begin():
        corp, secret = _sync_secret(db, tenant_id)
        corp_id = corp.corp_id
    try:
        departments = api.list_departments(corp_id, secret)
        members: dict[str, dict] = {}
        for department in departments:
            for item in api.list_members(corp_id, secret, str(department['id'])):
                entry = members.setdefault(str(item['userid']), {'name': '', 'department': []})
                entry['name'] = str(item.get('name') or entry['name'] or '')
                for dept in item.get('department') or [department['id']]:
                    if str(dept) not in entry['department']:
                        entry['department'].append(str(dept))
    except WeComError as exc:
        with db.begin():
            corp = db.get(WeComCorpRecord, tenant_id)
            corp.sync_status, corp.sync_error = 'failed', str(exc)[:500]
        raise
    stats = {'departments': len(departments), 'members': len(members), 'left': 0}
    with db.begin():
        _apply_departments(db, tenant_id, departments)
        now = utc_now()
        known = {row.userid: row for row in db.scalars(select(WeComMemberRecord).where(
            WeComMemberRecord.tenant_id == tenant_id))}
        for userid, data in members.items():
            row = known.get(userid)
            if row is None:
                identity = db.scalar(select(UserIdentityRecord).where(
                    UserIdentityRecord.provider == WECOM_PROVIDER, UserIdentityRecord.scope == corp_id,
                    UserIdentityRecord.external_id == userid))
                row = WeComMemberRecord(tenant_id=tenant_id, userid=userid,
                                        user_id=identity.user_id if identity else None)
                db.add(row)
            row.name, row.department_ids, row.active, row.synced_at = data['name'][:160], data['department'], True, now
            db.flush()
            if row.user_id is not None:
                membership = db.get(MembershipRecord, (tenant_id, row.user_id))
                if membership is not None and membership.status == 'active':
                    _place_member(db, tenant_id, row.user_id, row.department_ids)
        for userid, row in known.items():
            if userid not in members and row.active:
                stats['left'] += int(revoke_member(db, tenant_id, row, 'not_in_directory'))
        corp = db.get(WeComCorpRecord, tenant_id)
        corp.sync_status, corp.sync_error, corp.synced_at = 'ok', None, now
        audit(db, tenant_id, _system_actor(db, tenant_id), 'wecom.directory_synced', 'tenant', str(tenant_id),
              {**stats, 'by': 'wecom'})
    return stats


def request_sync(db: Session, principal: Principal, tenant_id: UUID) -> None:
    """Ask the worker to sync soon (the admin console's “sync now”)."""
    with db.begin():
        _manager(db, principal, tenant_id)
        corp = db.get(WeComCorpRecord, tenant_id)
        if corp is None:
            raise NotFound('WeCom is not configured')
        corp.sync_status = 'requested'


def due_for_sync(db: Session) -> list[UUID]:
    from nexus_platform.auth.sessions import aware
    cutoff = utc_now() - SYNC_INTERVAL
    rows = db.scalars(select(WeComCorpRecord)).all()
    return [row.tenant_id for row in rows
            if row.sync_status in ('never', 'requested') or row.synced_at is None or aware(row.synced_at) < cutoff]


# ---------------------------------------------------------------------------------------------- callbacks

def _crypto(db: Session, tenant_id: UUID) -> CallbackCrypto:
    corp = db.get(WeComCorpRecord, tenant_id)
    if corp is None or not corp.callback_token_ciphertext or not corp.encoding_aes_key_ciphertext:
        raise NotFound('Callback is not configured')
    return CallbackCrypto(_open(tenant_id, corp.callback_token_ciphertext),
                          _open(tenant_id, corp.encoding_aes_key_ciphertext), corp.corp_id)


def verify_url(db: Session, tenant_id: UUID, *, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
    """WeCom's URL check: return the decrypted ``echostr``."""
    with db.begin():
        crypto = _crypto(db, tenant_id)
    try:
        return crypto.decrypt(msg_signature, timestamp, nonce, echostr)
    except CallbackError as exc:
        raise Forbidden('Invalid WeCom callback') from exc


def decrypt_event(db: Session, tenant_id: UUID, *, msg_signature: str, timestamp: str, nonce: str,
                  body: str) -> ElementTree.Element:
    """Authenticate a pushed callback and return the inner message. The outer XML is not parsed before the
    signature is checked: only the ``Encrypt`` field is extracted."""
    match = _ENCRYPT.search(body or '')
    if match is None:
        raise Forbidden('Invalid WeCom callback')
    with db.begin():
        crypto = _crypto(db, tenant_id)
    try:
        return ElementTree.fromstring(crypto.decrypt(msg_signature, timestamp, nonce, match.group(1)))
    except (CallbackError, ElementTree.ParseError) as exc:
        raise Forbidden('Invalid WeCom callback') from exc


def handle_contact_event(db: Session, tenant_id: UUID, message: ElementTree.Element) -> str:
    """Apply a directory change: a deleted member leaves at once; any other change asks for a fresh sync."""
    if (message.findtext('Event') or '') != 'change_contact':
        return 'ignored'
    change, userid = message.findtext('ChangeType') or '', message.findtext('UserID') or ''
    with db.begin():
        corp = db.get(WeComCorpRecord, tenant_id)
        if change == 'delete_user' and userid:
            member = db.get(WeComMemberRecord, (tenant_id, userid))
            if member is not None:
                revoke_member(db, tenant_id, member, 'deleted_in_wecom')
            return 'member_left'
        corp.sync_status = 'requested'
    return 'sync_requested'
