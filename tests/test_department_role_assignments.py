"""部门批量角色分配：与单成员分配共用越权边界，事务内拒绝且不影响既有范围/幂等语义。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.main import app
from nexus_api.dependencies.platform import get_database_session, get_principal
from nexus_platform.errors import Conflict, NotFound
from nexus_platform.tenants import roles, membership
from nexus_platform.orgs import service as orgs
from nexus_platform.persistence.models import TenantUserRoleRecord, OrgUnitRecord, AuditRecord
from test_platform import database  # noqa: F401
from test_tenant_roles import OWNER, MEMBER, OTHER, _setup, _uid


def setup_department(factory):
    tid = _setup(factory)
    with factory() as db:
        root = orgs.create_unit(db, OWNER, tid, "公司")
        child = orgs.create_unit(db, OWNER, tid, "子部门", root.id)
    for person, unit in [(OWNER, root.id), (MEMBER, root.id), (OTHER, child.id)]:
        user = _uid(factory, person)
        with factory() as db:
            membership.place_member(db, OWNER, tid, user, unit)
    return tid, root.id, child.id


@pytest.mark.parametrize("permissions", [["members:manage"], ["roles:manage"], ["members:manage", "roles:manage"]])
def test_http_rejects_missing_permission_or_grants_outside_actor_without_partial_writes(database, permissions):
    tid, unit, _ = setup_department(database)
    user = _uid(database, MEMBER)
    with database() as db:
        manager = roles.create_role(db, OWNER, tid, "有限管理员", [], permissions)
        target = roles.create_role(db, OWNER, tid, "高权限", ["models"], ["models:manage"])
        roles.assign_role(db, OWNER, tid, user, manager.id)
    def session():
        with database() as db:
            yield db
    app.dependency_overrides[get_database_session] = session
    app.dependency_overrides[get_principal] = lambda: MEMBER
    try:
        with TestClient(app) as client:
            response = client.post(f"/api/v1/tenants/{tid}/org-units/{unit}/role-assignments", json={"role_id": str(target.id)})
            assert response.status_code == 403, response.text
    finally:
        app.dependency_overrides.clear()
    with database() as db:
        assert list(db.scalars(select(TenantUserRoleRecord).where(TenantUserRoleRecord.role_id == target.id))) == []
        assert not list(db.scalars(select(AuditRecord).where(AuditRecord.action == "tenant.role_assigned_to_unit")))


def test_subset_assignment_is_direct_only_skips_owner_and_is_repeatable(database):
    tid, unit, child = setup_department(database)
    user, other, owner = (_uid(database, p) for p in [MEMBER, OTHER, OWNER])
    with database() as db:
        manager = roles.create_role(db, OWNER, tid, "管理员", ["agents"], ["roles:manage", "members:manage", "agents:read"])
        target = roles.create_role(db, OWNER, tid, "读取", ["agents"], ["agents:read"])
        roles.assign_role(db, OWNER, tid, user, manager.id)
        first = membership.assign_role_to_unit(db, MEMBER, tid, unit, target.id)
        again = membership.assign_role_to_unit(db, MEMBER, tid, unit, target.id)
    assert first == {"assigned": [user], "skipped": []}
    assert again == {"assigned": [], "skipped": [user]}
    with database() as db:
        assert db.get(TenantUserRoleRecord, (tid, owner, target.id)) is None
        assert db.get(TenantUserRoleRecord, (tid, other, target.id)) is None
        assert len(list(db.scalars(select(AuditRecord).where(AuditRecord.action == "tenant.role_assigned_to_unit")))) == 2
    with database() as db:
        empty = orgs.create_unit(db, OWNER, tid, "空部门", unit)
        assert membership.assign_role_to_unit(db, OWNER, tid, empty.id, target.id) == {"assigned": [], "skipped": []}
    # 停用部门及跨企业角色仍拒绝。
    with database() as db, db.begin():
        db.get(OrgUnitRecord, child).status = "disabled"
    with database() as db, pytest.raises(Conflict):
        membership.assign_role_to_unit(db, OWNER, tid, child, target.id)
    foreign_tid = _setup(database)
    with database() as db:
        foreign = roles.create_role(db, OWNER, foreign_tid, "外部", [], [])
        with pytest.raises(NotFound):
            membership.assign_role_to_unit(db, OWNER, tid, unit, foreign.id)


def test_foreign_department_is_hidden_and_builtin_role_remains_assignable(database):
    tid, unit, _ = setup_department(database)
    other_tid = _setup(database)
    with database() as db:
        builtin = roles.create_role(db, OWNER, tid, "内置测试", [], ["audit:read"])
    from nexus_platform.persistence.models import TenantRoleRecord
    with database() as db, db.begin():
        db.get(TenantRoleRecord, builtin.id).builtin = True
    with database() as db:
        result = membership.assign_role_to_unit(db, OWNER, tid, unit, builtin.id)
        assert result["assigned"] == [_uid(database, MEMBER)]
    with database() as db, pytest.raises(NotFound):
        membership.assign_role_to_unit(db, OWNER, other_tid, unit, builtin.id)
