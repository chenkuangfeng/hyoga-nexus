"""WeCom binding is limited to the enterprise that records the corp (openspec 2026-11-03, section 7).

Uses the WeCom fake from tests/test_auth.py; the enterprise is given `wecom_corp_id = corp-1` directly, since
no screen sets it yet (the field is recorded only)."""
from urllib.parse import parse_qs, urlparse

from nexus_platform.auth import accounts
from nexus_platform.persistence.models import TenantRecord
from test_auth import CSRF, PASSWORD, _bootstrap_owner, _login, client  # noqa: F401  (fixture)
from test_platform import database  # noqa: F401  (fixture)


def _bind(client):
    start = client.post("/api/v1/auth/wecom/bind/start", headers=CSRF)
    assert start.status_code == 200, start.text
    state = parse_qs(urlparse(start.json()["authorize_url"]).query)["state"][0]
    return client.get(f"/api/v1/auth/wecom/callback?code=code-zhang&state={state}")


def test_only_members_of_the_recording_enterprise_can_bind_its_corp(client):
    tenant_id = _bootstrap_owner(client.factory)
    with client.factory() as db:
        db.get(TenantRecord, tenant_id).wecom_corp_id = "corp-1"
        db.commit()
    # An account without membership of the enterprise is refused.
    with client.factory() as db:
        accounts.register(db, username="outsider", email="outsider@example.com", password=PASSWORD,
                          space_kind="personal")
    assert _login(client, "outsider").status_code == 200
    refused = _bind(client)
    assert refused.status_code == 303 and "wecom=failed" in refused.headers["location"]
    # The enterprise owner can bind.
    assert _login(client, "owner-one").status_code == 200
    bound = _bind(client)
    assert bound.status_code == 303 and "wecom=bound" in bound.headers["location"]
