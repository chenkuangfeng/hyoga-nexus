from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nexus_platform.auth.accounts import authenticate_email
from nexus_platform.bootstrap import (
    DEFAULT_OWNER_EMAIL,
    DEFAULT_OWNER_PASSWORD,
    DEFAULT_SPACE_NAME,
    ensure_default_enterprise,
)
from nexus_platform.persistence.models import Base, MembershipRecord, TenantRecord, UserRecord


@pytest.fixture
def factory() -> Iterator[sessionmaker]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    engine.dispose()


def test_bootstrap_creates_space_owner_and_membership_once(factory: sessionmaker) -> None:
    with factory() as db:
        first = ensure_default_enterprise(db)
    assert first.created_owner and first.created_space and first.granted_membership

    with factory() as db:
        second = ensure_default_enterprise(db)
        spaces = db.scalar(select(func.count()).select_from(TenantRecord).where(TenantRecord.name == DEFAULT_SPACE_NAME))
        users = db.scalar(select(func.count()).select_from(UserRecord).where(UserRecord.email == DEFAULT_OWNER_EMAIL))
        memberships = db.scalar(select(func.count()).select_from(MembershipRecord))
    assert not (second.created_owner or second.created_space or second.granted_membership)
    assert second.space_id == first.space_id and second.owner_id == first.owner_id
    assert (spaces, users, memberships) == (1, 1, 1)


def test_bootstrap_space_is_enterprise_and_owner_can_sign_in(factory: sessionmaker) -> None:
    with factory() as db:
        result = ensure_default_enterprise(db)
    with factory() as db:
        space = db.get(TenantRecord, result.space_id)
        assert space is not None and space.kind == "enterprise" and space.status == "active"
    with factory() as db:
        token, _expires, user_id = authenticate_email(db, DEFAULT_OWNER_EMAIL, DEFAULT_OWNER_PASSWORD)
    assert token and user_id == result.owner_id


def test_bootstrap_reactivates_a_revoked_owner_membership(factory: sessionmaker) -> None:
    with factory() as db:
        result = ensure_default_enterprise(db)
    with factory() as db, db.begin():
        membership = db.get(MembershipRecord, (result.space_id, result.owner_id))
        membership.status = "revoked"
    with factory() as db:
        again = ensure_default_enterprise(db)
        membership = db.get(MembershipRecord, (result.space_id, result.owner_id))
    assert again.granted_membership and membership.status == "active" and membership.role == "owner"
