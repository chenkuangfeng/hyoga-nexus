"""IM channels bound to one agent (openspec 2026-11-11-enterprise-saas E4): who may add which channel, review of
personal bots, inbound messages becoming Runs of the member's own session, replies when the Run stops, and the
WeChat binding and long-poll. WeCom and iLink are faked."""
import asyncio
import threading
import xml.etree.ElementTree as ElementTree
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole, new_id, utc_now
from nexus_platform.agents import access as agent_access
from nexus_platform.agents.service import create_agent, publish_agent
from nexus_platform.channels import service
from nexus_platform.errors import Forbidden, InvalidConfiguration
from nexus_platform.models.service import create_model_profile
from nexus_platform.persistence.models import (AgentChannelRecord, ChannelDeliveryRecord, ChannelSessionBindingRecord,
                                               MessageRecord, RunRecord, UserIdentityRecord)
from nexus_platform.tenants import roles
from nexus_platform.tenants.policies import update_policy
from nexus_platform.tenants.service import add_member, create_tenant
from nexus_platform.wecom import service as wecom
from nexus_platform.wecom.client import WeComError

from test_platform import database  # noqa: F401 (pytest fixture)
from test_tenant_roles import _uid

OWNER = Principal('ch-owner', 'test')
MEMBER = Principal('ch-member', 'test')
OTHER = Principal('ch-other', 'test')
CORP = 'wwchannels'


class FakeWeCom:
    def __init__(self):
        self.sent, self.error = [], None

    def send_text(self, corp_id, secret, agentid, userid, content):
        if self.error:
            raise self.error
        self.sent.append((agentid, userid, content))


@pytest.fixture
def env(database, deployment_config):
    deployment_config(f'[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n')
    with database() as db:
        tid = create_tenant(db, OWNER, 'Acme').id
    for principal in (MEMBER, OTHER):
        with database() as db:
            add_member(db, OWNER, tid, principal, TenantRole.CONTRIBUTOR)
    with database() as db:
        _, model = create_model_profile(db, OWNER, tid, name='M', provider='openai', model_name='m',
                                        options={'base_url': 'https://model.example/v1'})

    def agent(principal, name, ownership):
        with database() as db:
            row = create_agent(db, principal, tid, name=name, description='', runtime_type='native', instructions='x',
                               model_profile_version_id=model.id, budgets={'max_rounds': 2}, bindings=[],
                               ownership=ownership)
        with database() as db:
            publish_agent(db, principal, tid, row.id)
        return row.id

    company = agent(OWNER, 'Helpdesk', 'enterprise')
    personal = agent(MEMBER, 'Mine', 'personal')
    return database, tid, company, personal


def _wecom_app(factory, tid, agent_id):
    with factory() as db:
        wecom.save_corp(db, OWNER, tid, corp_id=CORP)
    with factory() as db:
        return UUID(wecom.create_app(db, OWNER, tid, name='bot', wecom_agentid='3000001', secret='app-secret',
                                     purpose='agent', nexus_agent_id=agent_id)['id'])


def _wecom_identity(factory, principal, userid):
    """Link an existing member to a WeCom userid, as first entry through an app would."""
    user_id = _uid(factory, principal)
    with factory() as db, db.begin():
        db.add(UserIdentityRecord(id=new_id(), user_id=user_id, provider='wecom', scope=CORP, external_id=userid,
                                  verified_at=utc_now(), created_at=utc_now()))
    return user_id


def _grant_use(factory, tid, agent_id, principal):
    with factory() as db:
        role = roles.create_role(db, OWNER, tid, f'use-{principal.id}', ['agents'], ['agents:read'])
    with factory() as db:
        agent_access.set_agent_grants(db, OWNER, tid, role.id, agent_id, ['view', 'run'])
    with factory() as db:
        roles.assign_role(db, OWNER, tid, _uid(factory, principal), role.id)


def _message(sender, text, msg_id, agentid='3000001'):
    return ElementTree.fromstring(f'<xml><ToUserName>{CORP}</ToUserName><FromUserName>{sender}</FromUserName>'
                                  f'<MsgType>text</MsgType><Content>{text}</Content><MsgId>{msg_id}</MsgId>'
                                  f'<AgentID>{agentid}</AgentID></xml>')


def _finish(factory, run_id, text):
    from sqlalchemy import func
    with factory() as db, db.begin():
        run = db.get(RunRecord, run_id)
        run.status = 'completed'
        sequence = (db.scalar(select(func.max(MessageRecord.sequence)).where(
            MessageRecord.session_id == run.session_id)) or 0) + 1
        db.add(MessageRecord(id=new_id(), session_id=run.session_id, run_id=run.id, sequence=sequence, role='assistant',
                             content=text, runtime_metadata={}, created_at=utc_now()))


def test_who_may_add_which_channel(env):
    factory, tid, company, personal = env
    with factory() as db:
        with pytest.raises(InvalidConfiguration, match='personal agents only'):
            service.create_channel(db, OWNER, tid, company, kind='wechat')
    with factory() as db:
        with pytest.raises(InvalidConfiguration, match='enterprise agents only'):
            service.create_channel(db, MEMBER, tid, personal, kind='wecom_app')
    for kind in ('wecom_bot', 'qq'):
        with factory() as db:
            with pytest.raises(InvalidConfiguration, match='unverified'):
                service.create_channel(db, MEMBER, tid, personal, kind=kind)
    with factory() as db:
        with pytest.raises(Forbidden):  # only the agent's maintainers
            service.create_channel(db, OTHER, tid, personal, kind='wechat')
    with factory() as db:
        created = service.create_channel(db, MEMBER, tid, personal, kind='wechat')
    assert created['status'] == 'binding'
    with factory() as db:
        update_policy(db, OWNER, tid, {'personal_external_channels': False})
    with factory() as db:
        assert db.get(AgentChannelRecord, UUID(created['id'])).status == 'disabled'
    with factory() as db:
        with pytest.raises(Forbidden):
            service.create_channel(db, MEMBER, tid, personal, kind='wechat')


def test_review_queue_needs_agent_managers(env):
    factory, tid, _, personal = env
    with factory() as db, db.begin():
        row = AgentChannelRecord(id=new_id(), tenant_id=tid, agent_id=personal, kind='wecom_bot', name='bot',
                                 owner_user_id=_uid(factory, MEMBER), status='pending_review', created_at=utc_now(),
                                 updated_at=utc_now())
        db.add(row)
        channel_id = row.id
    with factory() as db:
        with pytest.raises(Forbidden):
            service.review_channel(db, MEMBER, tid, channel_id, approve=True)
    with factory() as db:
        with pytest.raises(InvalidConfiguration):
            service.review_channel(db, OWNER, tid, channel_id, approve=False)
    with factory() as db:
        assert [row['id'] for row in service.list_enterprise_channels(db, OWNER, tid, 'pending_review')] == [
            str(channel_id)]
    with factory() as db:
        assert service.review_channel(db, OWNER, tid, channel_id, approve=True)['status'] == 'active'
    with factory() as db:
        update_policy(db, OWNER, tid, {'personal_wecom_channels': 'disabled'})
    with factory() as db:
        assert db.get(AgentChannelRecord, channel_id).status == 'disabled'


def test_wecom_app_messages_become_runs_of_each_members_own_session(env):
    factory, tid, company, _ = env
    app_id = _wecom_app(factory, tid, company)
    with factory() as db:
        channel = service.create_channel(db, OWNER, tid, company, kind='wecom_app', wecom_app_id=app_id)
    _wecom_identity(factory, MEMBER, 'li')
    _wecom_identity(factory, OTHER, 'wang')
    _grant_use(factory, tid, company, MEMBER)
    with factory() as db:
        first = service.wecom_app_message(db, tid, _message('li', '你好', 'm1'))
    assert first.status == 'submitted' and first.run_id
    with factory() as db:
        assert service.wecom_app_message(db, tid, _message('li', '你好', 'm1')).status == 'duplicate'
    with factory() as db:
        refused = service.wecom_app_message(db, tid, _message('wang', 'hi', 'm2'))
    assert refused.reply == service.NO_ACCESS  # wang is a member but may not use the agent
    with factory() as db:
        stranger = service.wecom_app_message(db, tid, _message('zhao', 'hi', 'm3'))
    assert stranger.reply == service.NOT_MEMBER
    _grant_use(factory, tid, company, OTHER)
    with factory() as db:
        second = service.wecom_app_message(db, tid, _message('wang', 'hi', 'm4'))
    with factory() as db:
        bindings = db.scalars(select(ChannelSessionBindingRecord)).all()
        assert len({row.session_id for row in bindings}) == 2  # members never share a session
        assert db.get(RunRecord, second.run_id).session_id != db.get(RunRecord, first.run_id).session_id
    assert channel['kind'] == 'wecom_app'


def test_replies_are_sent_when_the_run_stops_and_retried_only_when_retryable(env):
    from nexus_worker.channels import delivery_tick
    factory, tid, company, _ = env
    app_id = _wecom_app(factory, tid, company)
    with factory() as db:
        service.create_channel(db, OWNER, tid, company, kind='wecom_app', wecom_app_id=app_id)
    _wecom_identity(factory, MEMBER, 'li')
    _grant_use(factory, tid, company, MEMBER)
    with factory() as db:
        submitted = service.wecom_app_message(db, tid, _message('li', 'q', 'r1'))
    fake = FakeWeCom()
    assert delivery_tick(factory, wecom=fake) is False  # the Run has not stopped yet
    _finish(factory, submitted.run_id, '答案')
    fake.error = WeComError('unavailable', 'down')
    assert delivery_tick(factory, wecom=fake) is True
    with factory() as db:
        row = db.get(ChannelDeliveryRecord, submitted.run_id)
        assert (row.status, row.attempts) == ('pending', 1)
    fake.error = None
    delivery_tick(factory, wecom=fake)
    assert fake.sent == [('3000001', 'li', '答案')]
    with factory() as db:
        assert db.get(ChannelDeliveryRecord, submitted.run_id).status == 'sent'
    with factory() as db:
        refused = service.wecom_app_message(db, tid, _message('li', 'q2', 'r2'))
    _finish(factory, refused.run_id, 'x')
    fake.error = WeComError('rejected', 'no')
    delivery_tick(factory, wecom=fake)
    with factory() as db:
        assert db.get(ChannelDeliveryRecord, refused.run_id).status == 'failed'


class FakeLogin:
    async def fetch_qr(self):
        return {'qrcode': 'qr-token', 'qrcode_url': 'https://example.invalid/qr'}

    async def status(self, qrcode):
        assert qrcode == 'qr-token'
        return {'status': 'confirmed', 'bot_token': 'bot-token', 'ilink_user_id': 'me@im.wechat',
                'ilink_bot_id': 'bot@im.bot', 'baseurl': 'https://ilinkai.weixin.qq.com'}


class FakeILink:
    def __init__(self, stopped, messages):
        self.stopped, self.messages, self.sent = stopped, messages, []

    async def get_updates(self, cursor):
        self.stopped.set()
        return self.messages, 'cursor-2'

    async def send_text(self, to, text, context_token=''):
        self.sent.append((to, text))


def test_wechat_binding_and_long_poll_serve_only_the_owner(env):
    from nexus_worker.channels import _poll_wechat
    factory, tid, _, personal = env
    app.state.session_factory = factory
    app.state.ilink_login = FakeLogin()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: MEMBER
    try:
        with TestClient(app) as client:
            created = client.post(f'/api/v1/tenants/{tid}/agents/{personal}/channels', json={'kind': 'wechat'})
            assert created.status_code == 201, created.text
            channel_id = created.json()['id']
            assert client.post(f'/api/v1/tenants/{tid}/channels/{channel_id}/wechat/qr').json()['qrcode_url']
            confirmed = client.get(f'/api/v1/tenants/{tid}/channels/{channel_id}/wechat/status').json()
            assert confirmed['status'] == 'confirmed' and confirmed['channel']['status'] == 'active'
            listed = client.get(f'/api/v1/tenants/{tid}/agents/{personal}/channels').json()
            assert 'bot-token' not in str(listed) and listed['unverified_kinds'] == ['qq', 'wecom_bot']
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None
        app.state.ilink_login = None
    with factory() as db, db.begin():
        assert service.claim_channels(db, 'wechat', 'worker-1', lease_seconds=90, limit=5) == [UUID(channel_id)]
    with factory() as db, db.begin():
        assert service.claim_channels(db, 'wechat', 'worker-2', lease_seconds=90, limit=5) == []  # one holder
    stopped = threading.Event()
    fake = FakeILink(stopped, [
        {'id': '1', 'from': 'someone-else', 'text': 'hi', 'context_token': 'c1'},
        {'id': '2', 'from': 'me@im.wechat', 'text': '帮我总结', 'context_token': 'c2'},
    ])
    asyncio.run(_poll_wechat(factory, UUID(channel_id), 'worker-1', stopped, lambda credentials: fake))
    with factory() as db:
        deliveries = db.scalars(select(ChannelDeliveryRecord)).all()
        assert [(row.recipient, row.reply_context) for row in deliveries] == [('me@im.wechat', 'c2')]
        assert db.get(AgentChannelRecord, UUID(channel_id)).cursor == 'cursor-2'
