"""IM channels bound to one agent (openspec 2026-11-11-enterprise-saas E4, decision 6; design section 7).

Who may add which channel:

============  ====================================  ===========================================================
kind          enterprise agent                      personal agent (its creator)
============  ====================================  ===========================================================
wecom_app     ``enterprise_agents:manage``; active   not allowed (apps are registered by administrators)
wecom_bot     ``enterprise_agents:manage``; active   policy ``personal_wecom_channels``: review / open / disabled
wechat, qq    not allowed                           policy ``personal_external_channels``; serves the creator only
============  ====================================  ===========================================================

Kinds whose platform conditions could not be verified are listed in ``UNVERIFIED`` and cannot be created.

Inbound messages (:func:`process_inbound`) are deduplicated, mapped to a member, checked against the channel state,
the enterprise policy and the member's use of the agent, then submitted as a Run of the member's session for that
(channel, conversation, member). A :class:`ChannelDeliveryRecord` remembers the reply owed; the worker sends it when
the Run stops (:func:`pending_replies` / :func:`mark_delivery`). Refusals are answered at once.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus_core.platform import Principal, new_id, utc_now
from nexus_platform.agents.access import ENTERPRISE, PERSONAL, can_maintain_agent, can_use_agent
from nexus_platform.authz.audit import audit
from nexus_platform.authz.permissions import effective_permissions
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound
from nexus_platform.identity.service import require_membership, require_tenant, resolve_user
from nexus_platform.orgs.access import membership_is_active
from nexus_platform.persistence.models import (AgentChannelRecord, AgentRecord, ChannelDeliveryRecord,
                                               ChannelMessageRecord, ChannelSessionBindingRecord, MembershipRecord,
                                               MessageRecord, RunRecord, UserIdentityRecord, WeComAppRecord,
                                               WeComCorpRecord)
from nexus_platform.tenants.policies import get_policy
from nexus_platform.wecom.service import _open, _seal

KINDS = ('wecom_app', 'wecom_bot', 'wechat', 'qq')
#: Platform conditions not verified yet (design 7.4): these kinds cannot be created.
UNVERIFIED = frozenset({'wecom_bot', 'qq'})
ENTERPRISE_KINDS = frozenset({'wecom_app', 'wecom_bot'})
PERSONAL_KINDS = frozenset({'wecom_bot', 'wechat', 'qq'})
STOPPED = frozenset({'completed', 'failed', 'cancelled', 'interrupted', 'waiting_input', 'waiting_approval'})
REPLY_LIMIT = 1800
NO_ACCESS = '你没有使用这个智能体的权限，请联系企业管理员。'
NOT_MEMBER = '你还不是这个企业的成员，或者账号尚未开通。'


def channel_view(row: AgentChannelRecord) -> dict[str, Any]:
    return {'id': str(row.id), 'agent_id': str(row.agent_id), 'kind': row.kind, 'name': row.name,
            'status': row.status, 'owner_user_id': str(row.owner_user_id),
            'wecom_app_id': str(row.wecom_app_id) if row.wecom_app_id else None,
            'bound': bool(row.bound_external_id), 'review_note': row.review_note,
            'created_at': row.created_at.isoformat(), 'updated_at': row.updated_at.isoformat()}


def _agent(db: Session, tenant_id: UUID, agent_id: UUID) -> AgentRecord:
    agent = db.get(AgentRecord, agent_id)
    if agent is None or agent.tenant_id != tenant_id or agent.status == 'archived':
        raise NotFound('Agent not found')
    return agent


def _actor(db: Session, principal: Principal, tenant_id: UUID):
    user = resolve_user(db, principal)
    require_tenant(db, tenant_id)
    require_membership(db, tenant_id, user.id)
    return user


def _manages_channels(db: Session, tenant_id: UUID, user_id: UUID) -> bool:
    return effective_permissions(db, tenant_id, user_id).allows_api('enterprise_agents:manage')


# ---------------------------------------------------------------------------------------------- management

def create_channel(db: Session, principal: Principal, tenant_id: UUID, agent_id: UUID, *, kind: str,
                   name: str = '', wecom_app_id: UUID | None = None, config: dict[str, Any] | None = None
                   ) -> dict[str, Any]:
    if kind not in KINDS:
        raise InvalidConfiguration('Unknown channel kind')
    if kind in UNVERIFIED:
        raise InvalidConfiguration('channel_kind_unverified: this channel kind is not available yet')
    with db.begin():
        user = _actor(db, principal, tenant_id)
        agent = _agent(db, tenant_id, agent_id)
        if not can_maintain_agent(db, tenant_id, user.id, agent):
            raise Forbidden("Only the agent's maintainers can add channels")
        policy = get_policy(db, tenant_id)
        if agent.ownership == ENTERPRISE:
            if kind not in ENTERPRISE_KINDS:
                raise InvalidConfiguration('WeChat and QQ channels are for personal agents only')
            status = 'active'
        else:
            if kind not in PERSONAL_KINDS:
                raise InvalidConfiguration('WeCom app channels are for enterprise agents only')
            if kind == 'wecom_bot':
                if policy.personal_wecom_channels == 'disabled':
                    raise Forbidden('Your enterprise does not allow WeCom bots on personal agents')
                status = 'pending_review' if policy.personal_wecom_channels == 'review' else 'active'
            else:
                if not policy.personal_external_channels:
                    raise Forbidden('Your enterprise does not allow WeChat or QQ channels')
                status = 'binding'
        if kind == 'wecom_app':
            app = db.get(WeComAppRecord, wecom_app_id) if wecom_app_id else None
            if app is None or app.tenant_id != tenant_id or app.purpose != 'agent' or app.nexus_agent_id != agent.id:
                raise InvalidConfiguration('Choose the WeCom app registered for this agent')
            if db.scalar(select(AgentChannelRecord.id).where(AgentChannelRecord.wecom_app_id == app.id)):
                raise Conflict('This WeCom app already has a channel')
        now, channel_id = utc_now(), new_id()
        row = AgentChannelRecord(id=channel_id, tenant_id=tenant_id, agent_id=agent.id, kind=kind,
                                 name=(name or kind)[:80], owner_user_id=user.id, wecom_app_id=wecom_app_id,
                                 config_ciphertext=_seal(channel_id, json.dumps(config)) if config else None,
                                 status=status, created_at=now, updated_at=now)
        db.add(row)
        db.flush()
        audit(db, tenant_id, user.id, 'channel.created', 'agent_channel', str(row.id),
              {'kind': kind, 'agent_id': str(agent.id), 'status': status})
        return channel_view(row)


def list_agent_channels(db: Session, principal: Principal, tenant_id: UUID, agent_id: UUID) -> list[dict]:
    with db.begin():
        user = _actor(db, principal, tenant_id)
        agent = _agent(db, tenant_id, agent_id)
        if not can_maintain_agent(db, tenant_id, user.id, agent):
            raise Forbidden("Only the agent's maintainers can see its channels")
        rows = db.scalars(select(AgentChannelRecord).where(AgentChannelRecord.agent_id == agent.id)
                          .order_by(AgentChannelRecord.created_at)).all()
        return [channel_view(row) for row in rows]


def list_enterprise_channels(db: Session, principal: Principal, tenant_id: UUID, status: str | None = None
                             ) -> list[dict]:
    """The admin console's channel overview and review queue (``enterprise_agents:manage``)."""
    with db.begin():
        user = _actor(db, principal, tenant_id)
        if not _manages_channels(db, tenant_id, user.id):
            raise Forbidden('Your tenant role does not allow this action')
        query = select(AgentChannelRecord).where(AgentChannelRecord.tenant_id == tenant_id)
        if status:
            query = query.where(AgentChannelRecord.status == status)
        return [channel_view(row) for row in db.scalars(query.order_by(AgentChannelRecord.created_at)).all()]


def _channel(db: Session, tenant_id: UUID, channel_id: UUID) -> AgentChannelRecord:
    row = db.get(AgentChannelRecord, channel_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound('Channel not found')
    return row


def review_channel(db: Session, principal: Principal, tenant_id: UUID, channel_id: UUID, *, approve: bool,
                   note: str = '') -> dict[str, Any]:
    with db.begin():
        user = _actor(db, principal, tenant_id)
        if not _manages_channels(db, tenant_id, user.id):
            raise Forbidden('Your tenant role does not allow this action')
        row = _channel(db, tenant_id, channel_id)
        if row.status != 'pending_review':
            raise Conflict('The channel is not waiting for review')
        if not approve and not note.strip():
            raise InvalidConfiguration('A reason is required to reject')
        row.status = 'active' if approve else 'rejected'
        row.review_note, row.reviewed_by, row.reviewed_at, row.updated_at = (note.strip()[:500] or None, user.id,
                                                                            utc_now(), utc_now())
        audit(db, tenant_id, user.id, 'channel.approved' if approve else 'channel.rejected', 'agent_channel',
              str(row.id), {'note': row.review_note})
        return channel_view(row)


def disable_channel(db: Session, principal: Principal, tenant_id: UUID, channel_id: UUID, *, delete: bool = False
                    ) -> None:
    """Stop (or delete) a channel: its maintainers, or enterprise agent managers for any channel."""
    with db.begin():
        user = _actor(db, principal, tenant_id)
        row = _channel(db, tenant_id, channel_id)
        agent = db.get(AgentRecord, row.agent_id)
        if not (_manages_channels(db, tenant_id, user.id) or can_maintain_agent(db, tenant_id, user.id, agent)):
            raise Forbidden('You cannot change this channel')
        if delete:
            db.delete(row)
        else:
            row.status, row.lease_owner, row.lease_until, row.updated_at = 'disabled', None, None, utc_now()
        audit(db, tenant_id, user.id, 'channel.deleted' if delete else 'channel.disabled', 'agent_channel',
              str(channel_id), {})


def enforce_policy(db: Session, tenant_id: UUID) -> int:
    """After the policy tightens, stop the personal channels it no longer allows; returns how many."""
    policy = get_policy(db, tenant_id)
    stopped = 0
    rows = db.scalars(select(AgentChannelRecord, AgentRecord)
                      .join(AgentRecord, AgentRecord.id == AgentChannelRecord.agent_id)
                      .where(AgentChannelRecord.tenant_id == tenant_id,
                             AgentChannelRecord.status.in_(('active', 'pending_review', 'binding')),
                             AgentRecord.ownership == PERSONAL)).all()
    for row in rows:
        refused = ((row.kind == 'wecom_bot' and policy.personal_wecom_channels == 'disabled')
                   or (row.kind in ('wechat', 'qq') and not policy.personal_external_channels))
        if refused:
            row.status, row.lease_owner, row.lease_until, row.updated_at = 'disabled', None, None, utc_now()
            stopped += 1
    return stopped


def usable(db: Session, row: AgentChannelRecord) -> bool:
    """Whether a channel may serve messages right now (state, agent, owner, policy)."""
    if row.status != 'active':
        return False
    agent = db.get(AgentRecord, row.agent_id)
    if agent is None or agent.status == 'archived' or agent.published_version_id is None:
        return False
    if not membership_is_active(db, db.get(MembershipRecord, (row.tenant_id, row.owner_user_id))):
        return False
    if agent.ownership == PERSONAL:
        policy = get_policy(db, row.tenant_id)
        if row.kind == 'wecom_bot' and policy.personal_wecom_channels == 'disabled':
            return False
        if row.kind in ('wechat', 'qq') and not policy.personal_external_channels:
            return False
    return True


# ---------------------------------------------------------------------------------------------- binding (WeChat)

def channel_config(row: AgentChannelRecord) -> dict[str, Any]:
    return json.loads(_open(row.id, row.config_ciphertext)) if row.config_ciphertext else {}


def store_config(row: AgentChannelRecord, config: dict[str, Any]) -> None:
    row.config_ciphertext = _seal(row.id, json.dumps(config))


def complete_binding(db: Session, tenant_id: UUID, channel_id: UUID, *, external_user: str,
                     credentials: dict[str, Any]) -> dict[str, Any]:
    """The owner confirmed the QR code: keep the credentials and the owner's platform id, then activate."""
    row = _channel(db, tenant_id, channel_id)
    if row.status != 'binding':
        raise Conflict('The channel is not waiting for binding')
    store_config(row, credentials)
    row.bound_external_id, row.status, row.cursor, row.updated_at = external_user[:128], 'active', None, utc_now()
    audit(db, tenant_id, row.owner_user_id, 'channel.bound', 'agent_channel', str(row.id), {'kind': row.kind})
    return channel_view(row)


def new_claim_code(row: AgentChannelRecord) -> str:
    """A one-time code the owner sends to a QQ bot to claim it (QQ is unverified; kept for the claim rule)."""
    code = f'{secrets.randbelow(10 ** 6):06d}'
    row.claim_code_hash = hashlib.sha256(code.encode()).hexdigest()
    return code


# ---------------------------------------------------------------------------------------------- inbound

@dataclass(frozen=True)
class Inbound:
    """``reply`` is an immediate answer (refusals); ``run_id`` is set when a Run was submitted."""
    status: str
    reply: str | None = None
    run_id: UUID | None = None


def _principal_for(db: Session, user_id: UUID, prefer_provider: str | None = None) -> Principal:
    identities = db.scalars(select(UserIdentityRecord).where(UserIdentityRecord.user_id == user_id)
                            .order_by(UserIdentityRecord.created_at)).all()
    chosen = next((row for row in identities if row.provider == prefer_provider), identities[0] if identities else None)
    if chosen is None:
        raise Forbidden(NOT_MEMBER)
    return Principal(id=chosen.external_id, issuer=chosen.provider, scope=chosen.scope)


def _member_for(db: Session, row: AgentChannelRecord, sender: str, text: str) -> tuple[UUID | None, str | None]:
    """(user id, immediate reply). WeCom channels map the sender; WeChat / QQ serve the bound owner only."""
    if row.kind in ('wecom_app', 'wecom_bot'):
        corp = db.get(WeComCorpRecord, row.tenant_id)
        identity = db.scalar(select(UserIdentityRecord).where(
            UserIdentityRecord.provider == 'wecom', UserIdentityRecord.scope == (corp.corp_id if corp else ''),
            UserIdentityRecord.external_id == sender)) if corp else None
        if identity is None:
            return None, NOT_MEMBER
        return identity.user_id, None
    if row.bound_external_id is None and row.kind == 'qq' and row.claim_code_hash:
        if hashlib.sha256(text.strip().encode()).hexdigest() == row.claim_code_hash:
            row.bound_external_id, row.claim_code_hash = sender[:128], None
            return None, '绑定成功，现在可以直接和智能体对话了。'
        return None, None
    if sender != row.bound_external_id:
        return None, None  # someone else wrote to the owner's bot: ignore silently
    return row.owner_user_id, None


def process_inbound(db: Session, channel_id: UUID, *, sender: str, conversation: str, text: str,
                    message_id: str, reply_context: str | None = None) -> Inbound:
    from nexus_platform.runs.compatibility import create_run
    from nexus_platform.sessions.service import create_session
    text = (text or '').strip()
    with db.begin():
        row = db.get(AgentChannelRecord, channel_id)
        if row is None:
            return Inbound('unknown_channel')
        try:
            with db.begin_nested():
                db.add(ChannelMessageRecord(channel_id=row.id, message_id=str(message_id)[:128],
                                            received_at=utc_now()))
        except IntegrityError:
            return Inbound('duplicate')
        if not usable(db, row) or not text:
            return Inbound('ignored')
        user_id, reply = _member_for(db, row, sender, text)
        if user_id is None:
            return Inbound('refused' if reply else 'ignored', reply=reply)
        agent = db.get(AgentRecord, row.agent_id)
        if not membership_is_active(db, db.get(MembershipRecord, (row.tenant_id, user_id))):
            return Inbound('refused', reply=NOT_MEMBER)
        if not can_use_agent(db, row.tenant_id, user_id, agent):
            return Inbound('refused', reply=NO_ACCESS)
        principal = _principal_for(db, user_id, 'wecom' if row.kind.startswith('wecom') else None)
        binding = db.scalar(select(ChannelSessionBindingRecord).where(
            ChannelSessionBindingRecord.channel_id == row.id,
            ChannelSessionBindingRecord.conversation == conversation[:255],
            ChannelSessionBindingRecord.user_id == user_id))
        tenant_id, version_id, kind = row.tenant_id, agent.published_version_id, row.kind
    if binding is None:
        session = create_session(db, principal, tenant_id, agent_version_id=version_id, title=f'{kind} 对话')
        with db.begin():
            binding = ChannelSessionBindingRecord(id=new_id(), channel_id=channel_id, conversation=conversation[:255],
                                                  user_id=user_id, session_id=session.id, created_at=utc_now())
            db.add(binding)
        session_id = session.id
    else:
        session_id = binding.session_id
    run, _ = create_run(db, principal, tenant_id, session_id, message=text,
                        idempotency_key=f'channel:{channel_id}:{message_id}'[:128])
    with db.begin():
        now = utc_now()
        if db.get(ChannelDeliveryRecord, run.id) is None:
            db.add(ChannelDeliveryRecord(run_id=run.id, channel_id=channel_id, conversation=conversation[:255],
                                         recipient=sender[:128], reply_context=reply_context, status='pending',
                                         attempts=0, created_at=now, updated_at=now))
    return Inbound('submitted', run_id=run.id)


# ---------------------------------------------------------------------------------------------- replies

@dataclass(frozen=True)
class Reply:
    run_id: UUID
    channel_id: UUID
    kind: str
    recipient: str
    reply_context: str | None
    text: str


def reply_text(db: Session, run: RunRecord, workspace_url: str = '') -> str:
    if run.status in ('waiting_approval', 'waiting_input'):
        return f'这一步需要你确认，请到工作台处理：{workspace_url}/sessions/{run.session_id}'.strip()
    if run.status != 'completed':
        return '这次没有处理成功，请稍后再试，或到工作台查看。'
    message = db.scalar(select(MessageRecord).where(MessageRecord.run_id == run.id, MessageRecord.role == 'assistant')
                        .order_by(MessageRecord.sequence.desc()).limit(1))
    text = (message.content if message else '').strip() or '（没有回复内容）'
    if len(text) > REPLY_LIMIT:
        text = text[:REPLY_LIMIT] + f'…\n完整内容请到工作台查看：{workspace_url}/sessions/{run.session_id}'.rstrip()
    return text


def pending_replies(db: Session, *, limit: int = 20, workspace_url: str = '') -> list[Reply]:
    """Replies owed for Runs that have stopped (finished, or waiting for the member in the workspace)."""
    rows = db.execute(select(ChannelDeliveryRecord, RunRecord, AgentChannelRecord)
                      .join(RunRecord, RunRecord.id == ChannelDeliveryRecord.run_id)
                      .join(AgentChannelRecord, AgentChannelRecord.id == ChannelDeliveryRecord.channel_id)
                      .where(ChannelDeliveryRecord.status == 'pending', RunRecord.status.in_(STOPPED))
                      .order_by(ChannelDeliveryRecord.created_at).limit(limit)).all()
    return [Reply(delivery.run_id, channel.id, channel.kind, delivery.recipient, delivery.reply_context,
                  reply_text(db, run, workspace_url)) for delivery, run, channel in rows]


def mark_delivery(db: Session, run_id: UUID, *, sent: bool, error: str = '', retry: bool = False,
                  max_attempts: int = 3) -> None:
    """Record a send. Only an explicit retryable failure (``retry``) is tried again, up to ``max_attempts``."""
    row = db.get(ChannelDeliveryRecord, run_id)
    if row is None:
        return
    row.attempts += 1
    row.updated_at = utc_now()
    if sent:
        row.status, row.last_error = 'sent', None
    elif retry and row.attempts < max_attempts:
        row.last_error = error[:300]
    else:
        row.status, row.last_error = 'failed', error[:300]


# ---------------------------------------------------------------------------------------------- WeCom app messages

def wecom_app_message(db: Session, tenant_id: UUID, message) -> Inbound:
    """Route a decrypted WeCom application message (``MsgType`` text) to the channel of its agent app."""
    agentid = (message.findtext('AgentID') or '').strip()
    with db.begin():
        app = db.scalar(select(WeComAppRecord).where(WeComAppRecord.tenant_id == tenant_id,
                                                     WeComAppRecord.wecom_agentid == agentid))
        channel = db.scalar(select(AgentChannelRecord).where(AgentChannelRecord.wecom_app_id == app.id)) if app else None
        channel_id = channel.id if channel else None
    if channel_id is None or (message.findtext('MsgType') or '') != 'text':
        return Inbound('ignored')
    sender = message.findtext('FromUserName') or ''
    return process_inbound(db, channel_id, sender=sender, conversation=sender, text=message.findtext('Content') or '',
                           message_id=message.findtext('MsgId') or f'{sender}:{message.findtext("CreateTime")}')


def wecom_app_target(db: Session, channel_id: UUID) -> tuple[str, str, str]:
    """(corp id, app secret, AgentId) to send a reply through a WeCom app channel."""
    channel = db.get(AgentChannelRecord, channel_id)
    app = db.get(WeComAppRecord, channel.wecom_app_id)
    corp = db.get(WeComCorpRecord, channel.tenant_id)
    return corp.corp_id, _open(app.id, app.secret_ciphertext), app.wecom_agentid


# ---------------------------------------------------------------------------------------------- leases

def claim_channels(db: Session, kind: str, owner: str, *, lease_seconds: int, limit: int) -> list[UUID]:
    """Take the lease of active channels of one kind whose lease expired, so one worker holds each connection."""
    from datetime import timedelta
    from nexus_platform.auth.sessions import aware
    now = utc_now()
    rows = db.scalars(select(AgentChannelRecord).where(AgentChannelRecord.kind == kind,
                                                       AgentChannelRecord.status == 'active')
                      .with_for_update(skip_locked=True)).all()
    claimed = []
    for row in rows:
        if len(claimed) >= limit:
            break
        if row.lease_until is not None and aware(row.lease_until) > now and row.lease_owner != owner:
            continue
        if not usable(db, row):
            continue
        row.lease_owner, row.lease_until = owner, now + timedelta(seconds=lease_seconds)
        claimed.append(row.id)
    return claimed


def renew_lease(db: Session, channel_id: UUID, owner: str, *, lease_seconds: int) -> bool:
    """Extend a lease this worker holds; False when it was lost or the channel can no longer serve."""
    from datetime import timedelta
    row = db.get(AgentChannelRecord, channel_id)
    if row is None or row.lease_owner != owner or not usable(db, row):
        return False
    row.lease_until = utc_now() + timedelta(seconds=lease_seconds)
    return True
