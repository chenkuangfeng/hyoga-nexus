"""Enterprise WeCom self-built apps: configuration, entry and QR sign-in with first-entry accounts, directory sync
with departures, and authenticated callbacks (openspec 2026-11-11-enterprise-saas E3). WeCom itself is faked."""
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_api.main import app
from nexus_core.platform import Principal, TenantRole
from nexus_platform.persistence.models import (MembershipRecord, OrgUnitRecord, TenantRecord, UserOrgUnitRecord,
                                               WeComMemberRecord)
from nexus_platform.tenants.service import add_member, create_tenant
from nexus_platform.wecom import service
from nexus_platform.wecom.client import WeComError
from nexus_platform.wecom.crypto import CallbackCrypto

from test_platform import database  # noqa: F401 (pytest fixture)

OWNER = Principal('wc-owner', 'test')
MEMBER = Principal('wc-member', 'test')
CORP = 'wwcorp0001'
AES_KEY = 'a' * 43


class FakeWeCom:
    def __init__(self):
        self.codes = {}  # code -> userid
        self.departments = [{'id': '1', 'name': 'Acme', 'parentid': '0'},
                            {'id': '2', 'name': 'Sales', 'parentid': '1'}]
        self.members = {'1': [{'userid': 'zhang', 'name': '张三', 'department': ['1']}],
                        '2': [{'userid': 'li', 'name': '李四', 'department': ['2']}]}
        self.fail = False

    def get_userid(self, corp_id, secret, code):
        assert (corp_id, secret) == (CORP, 'app-secret')
        if code not in self.codes:
            raise WeComError('rejected', 'bad code')
        return self.codes[code]

    def list_departments(self, corp_id, secret):
        if self.fail:
            raise WeComError('unavailable', 'down')
        return list(self.departments)

    def list_members(self, corp_id, secret, department_id):
        return list(self.members.get(department_id, []))

    def send_text(self, *args):
        pass


@pytest.fixture
def env(database, deployment_config):
    deployment_config(f'[security]\ncredential_encryption_key = "{Fernet.generate_key().decode()}"\n')
    with database() as db:
        tenant = create_tenant(db, OWNER, 'Acme')
        tid = tenant.id
    with database() as db:
        add_member(db, OWNER, tid, MEMBER, TenantRole.CONTRIBUTOR)
    with database() as db, db.begin():
        db.get(TenantRecord, tid).code = 'acme'
    fake = FakeWeCom()
    app.state.session_factory = database
    app.state.wecom_api = fake

    def override_db():
        with database() as db:
            yield db

    current = {'principal': OWNER}
    app.dependency_overrides[get_database_session] = override_db
    app.dependency_overrides[get_principal] = lambda: current['principal']
    try:
        with TestClient(app) as client:
            yield client, database, tid, fake, current
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = None
        app.state.wecom_api = None


def _configure(client, tid, *, purpose='workspace', agentid='1000001', qr=True, agent=None):
    base = f'/api/v1/tenants/{tid}/admin/wecom'
    saved = client.put(base, json={'corp_id': CORP, 'callback_token': 'tok', 'encoding_aes_key': AES_KEY})
    assert saved.status_code == 200, saved.text
    created = client.post(base + '/apps', json={'name': purpose, 'wecom_agentid': agentid, 'secret': 'app-secret',
                                                'purpose': purpose, 'qr_login': qr, 'nexus_agent_id': agent})
    assert created.status_code == 201, created.text
    return created.json()


def _enter(client, fake, app_id, code, userid):
    fake.codes[code] = userid
    entry = client.get(f'/wecom/apps/{app_id}/entry', follow_redirects=False)
    assert entry.status_code == 302 and entry.headers['location'].startswith('https://open.weixin.qq.com/')
    state = parse_qs(urlsplit(entry.headers['location'].split('#')[0]).query)['state'][0]
    return client.get(f'/wecom/apps/{app_id}/callback', params={'code': code, 'state': state},
                      follow_redirects=False)


def test_configuration_needs_org_manage_and_never_returns_secrets(env):
    client, factory, tid, fake, current = env
    created = _configure(client, tid)
    config = client.get(f'/api/v1/tenants/{tid}/admin/wecom').json()
    assert config['corp_id'] == CORP and config['callback_configured'] is True
    assert 'app-secret' not in str(config) and AES_KEY not in str(config)
    assert config['apps'][0]['entry_path'] == f"/wecom/apps/{created['id']}/entry"
    second = client.post(f'/api/v1/tenants/{tid}/admin/wecom/apps', json={
        'name': 'admin', 'wecom_agentid': '1000002', 'secret': 's', 'purpose': 'admin', 'qr_login': True})
    apps = {row['name']: row['qr_login'] for row in client.get(f'/api/v1/tenants/{tid}/admin/wecom').json()['apps']}
    assert second.status_code == 201 and apps == {'workspace': False, 'admin': True}  # one QR app at a time
    bad = client.post(f'/api/v1/tenants/{tid}/admin/wecom/apps', json={
        'name': 'bot', 'wecom_agentid': '1000003', 'secret': 's', 'purpose': 'agent'})
    assert bad.status_code == 422  # an agent app must name its agent
    current['principal'] = MEMBER
    assert client.get(f'/api/v1/tenants/{tid}/admin/wecom').status_code == 403


def test_sync_mirrors_departments_and_members_and_detects_departures(env):
    client, factory, tid, fake, _ = env
    _configure(client, tid)
    with factory() as db:
        assert service.sync_directory(db, fake, tid) == {'departments': 2, 'members': 2, 'left': 0}
    with factory() as db:
        units = {row.external_id: row for row in db.scalars(select(OrgUnitRecord).where(OrgUnitRecord.tenant_id == tid))}
        assert units['2'].name == 'Sales' and units['2'].parent_id == units['1'].id
        assert {row.userid for row in db.scalars(select(WeComMemberRecord))} == {'zhang', 'li'}
    fake.fail = True
    with factory() as db:
        with pytest.raises(WeComError):
            service.sync_directory(db, fake, tid)
    with factory() as db:
        assert client.get(f'/api/v1/tenants/{tid}/admin/wecom').json()['sync_status'] == 'failed'


def test_first_entry_creates_the_account_and_lands_by_purpose(env):
    client, factory, tid, fake, _ = env
    workspace = _configure(client, tid)
    with factory() as db:
        service.sync_directory(db, fake, tid)
    first = _enter(client, fake, workspace['id'], 'c1', 'li')
    assert first.status_code == 303 and first.headers['location'] == '/'
    assert first.cookies or 'set-cookie' in first.headers
    with factory() as db:
        member = db.get(WeComMemberRecord, (tid, 'li'))
        membership = db.get(MembershipRecord, (tid, member.user_id))
        assert (membership.role, membership.source, membership.status) == ('contributor', 'wecom', 'active')
        sales = db.scalar(select(OrgUnitRecord.id).where(OrgUnitRecord.external_id == '2'))
        assert db.get(UserOrgUnitRecord, (tid, member.user_id, sales)) is not None
    again = _enter(client, fake, workspace['id'], 'c2', 'li')  # the same account signs in again
    assert again.headers['location'] == '/'
    unknown = _enter(client, fake, workspace['id'], 'c3', 'stranger')
    assert unknown.headers['location'] == '/login?wecom=not_in_directory'
    reused = client.get(f"/wecom/apps/{workspace['id']}/callback", params={'code': 'c1', 'state': 'forged'},
                        follow_redirects=False)
    assert reused.headers['location'] == '/login?wecom=expired'
    fake.members['2'] = []  # li left the visible range: the next sync revokes the membership, the account stays
    with factory() as db:
        assert service.sync_directory(db, fake, tid)['left'] == 1
    with factory() as db:
        member = db.get(WeComMemberRecord, (tid, 'li'))
        assert db.get(MembershipRecord, (tid, member.user_id)).status == 'revoked'


def test_admin_and_agent_apps_land_on_their_pages(env):
    from test_resource_ownership import _agent  # noqa: F401
    from nexus_platform.agents.service import create_agent
    from nexus_platform.models.service import create_model_profile
    client, factory, tid, fake, _ = env
    with factory() as db:
        _, model = create_model_profile(db, OWNER, tid, name='M', provider='openai', model_name='m',
                                        options={'base_url': 'https://model.example/v1'})
    with factory() as db:
        agent = create_agent(db, OWNER, tid, name='Helpdesk', description='', runtime_type='native', instructions='x',
                             model_profile_version_id=model.id, budgets={'max_rounds': 2}, bindings=[],
                             ownership='enterprise')
    _configure(client, tid, purpose='admin', agentid='2000001', qr=False)
    created = client.post(f'/api/v1/tenants/{tid}/admin/wecom/apps', json={
        'name': 'bot', 'wecom_agentid': '2000002', 'secret': 'app-secret', 'purpose': 'agent',
        'nexus_agent_id': str(agent.id)}).json()
    duplicate = client.post(f'/api/v1/tenants/{tid}/admin/wecom/apps', json={
        'name': 'bot2', 'wecom_agentid': '2000003', 'secret': 'app-secret', 'purpose': 'agent',
        'nexus_agent_id': str(agent.id)})
    assert duplicate.status_code == 409
    with factory() as db:
        service.sync_directory(db, fake, tid)
    landed = _enter(client, fake, created['id'], 'c9', 'zhang')
    assert landed.headers['location'] == f'/agents/{agent.id}/chat'
    admin_app = client.get(f'/api/v1/tenants/{tid}/admin/wecom').json()['apps'][0]
    assert _enter(client, fake, admin_app['id'], 'c10', 'zhang').headers['location'] == '/enterprise/'


def test_qr_sign_in_uses_the_enterprise_code(env):
    client, factory, tid, fake, _ = env
    _configure(client, tid)
    started = client.get('/api/v1/auth/wecom/qr', params={'enterprise_code': 'acme'}, follow_redirects=False)
    assert started.status_code == 302 and started.headers['location'].startswith('https://login.work.weixin.qq.com/')
    assert client.get('/api/v1/auth/wecom/qr', params={'enterprise_code': 'nope'}).status_code == 404


def test_callbacks_are_authenticated_and_a_deleted_member_leaves(env):
    client, factory, tid, fake, _ = env
    workspace = _configure(client, tid)
    with factory() as db:
        service.sync_directory(db, fake, tid)
    _enter(client, fake, workspace['id'], 'c1', 'li')
    crypto = CallbackCrypto('tok', AES_KEY, CORP)
    path = f'/api/v1/integrations/wecom/{tid}/callback'
    echo, signature = crypto.encrypt('hello', '1', 'n')
    checked = client.get(path, params={'msg_signature': signature, 'timestamp': '1', 'nonce': 'n', 'echostr': echo})
    assert checked.status_code == 200 and checked.text == 'hello'
    assert client.get(path, params={'msg_signature': 'x', 'timestamp': '1', 'nonce': 'n',
                                    'echostr': echo}).status_code == 403
    event = ('<xml><MsgType>event</MsgType><Event>change_contact</Event><ChangeType>delete_user</ChangeType>'
             '<UserID>li</UserID></xml>')
    encrypted, signature = crypto.encrypt(event, '2', 'm')
    body = f'<xml><ToUserName>{CORP}</ToUserName><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>'
    pushed = client.post(path, params={'msg_signature': signature, 'timestamp': '2', 'nonce': 'm'}, content=body)
    assert pushed.status_code == 200 and pushed.text == 'success'
    with factory() as db:
        member = db.get(WeComMemberRecord, (tid, 'li'))
        assert not member.active and db.get(MembershipRecord, (tid, member.user_id)).status == 'revoked'
    assert _enter(client, fake, workspace['id'], 'c2', 'li').headers['location'] == '/login?wecom=not_in_directory'
    assert UUID(str(tid))


def test_worker_syncs_requested_enterprises(env):
    from nexus_worker import wecom_sync
    client, factory, tid, fake, _ = env
    _configure(client, tid)
    assert client.post(f'/api/v1/tenants/{tid}/admin/wecom/sync').status_code == 202
    wecom_sync._LAST_CHECK.clear()
    assert wecom_sync.wecom_tick(factory, api=fake) is True
    assert client.get(f'/api/v1/tenants/{tid}/admin/wecom').json()['sync_status'] == 'ok'
    wecom_sync._LAST_CHECK.clear()
    assert wecom_sync.wecom_tick(factory, api=fake) is False  # nothing due until tomorrow
