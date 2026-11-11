"""Sharing private skills into the space library (openspec 2026-11-07-skill-evolution, S5)."""
import pytest
from sqlalchemy import select

from nexus_core.platform import Principal, TenantRole
from nexus_platform.errors import Conflict, Forbidden, InvalidConfiguration, NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.models.provider_settings import context
from nexus_platform.persistence.models import AuditRecord, SkillRecord, SkillSubmissionRecord, SkillVersionRecord
from nexus_platform.skills import private, submissions
from nexus_platform.skills.service import SkillScanBlocked, publish
from nexus_platform.tenants.roles import assign_role, create_role
from nexus_platform.tenants.service import add_member
from test_platform import database  # noqa: F401  (pytest fixture)
from test_skills_platform import PRINCIPAL, _tenant
from test_skills_api import _client, teardown_function  # noqa: F401  (module level: pytest only runs teardown_function found here)

BOB = Principal(id='bob', issuer='test')
CARA = Principal(id='cara', issuer='test')
MD = '---\nname: my-notes\ndescription: Keeps my notes tidy\ntools: []\n---\n# Steps\nWrite short notes.\n'


@pytest.fixture
def world(database):
    """Owner alice, contributor bob who may submit, contributor cara who may not."""
    tenant, _ = _tenant(database)
    with database() as db:
        add_member(db, PRINCIPAL, tenant.id, BOB, TenantRole.CONTRIBUTOR)
        add_member(db, PRINCIPAL, tenant.id, CARA, TenantRole.CONTRIBUTOR)
    with database() as db:
        role = create_role(db, PRINCIPAL, tenant.id, 'Skill authors', [], ['skills:submit'])
        bob_id = resolve_user(db, BOB).id
        db.commit()
    with database() as db:
        assign_role(db, PRINCIPAL, tenant.id, bob_id, role.id)
    return tenant


def _uid(database, tenant, principal):
    with database() as db, db.begin():
        return context(db, principal, tenant.id)[0].id


def _private(database, tenant, principal, md=MD, files=None):
    uid = _uid(database, tenant, principal)
    with database() as db, db.begin():
        private.create(db, tenant.id, uid, md, files or {})
        private.save(db, tenant.id, uid, parse_name(md))
    return uid


def parse_name(md):
    return md.split('name: ')[1].split('\n')[0]


def _submit(database, tenant, principal=BOB, name='my-notes'):
    with database() as db:
        return submissions.submit(db, principal, tenant.id, name)


def test_only_holders_of_skills_submit_can_file_a_submission(database, world):
    for who in (BOB, CARA, PRINCIPAL):
        _private(database, world, who)
    assert _submit(database, world, BOB)['state'] == 'pending'
    with pytest.raises(Forbidden):  # a contributor without the permission
        _submit(database, world, CARA)
    assert _submit(database, world, PRINCIPAL)['state'] == 'pending'  # the owner holds every permission
    with database() as db, pytest.raises(NotFound):  # there is nothing to submit under another name
        submissions.submit(db, BOB, world.id, 'missing')


def test_the_permission_is_in_the_catalog_and_admins_hold_it_by_default():
    from nexus_platform.authz.catalog import API_PERMISSIONS
    from nexus_platform.authz.permissions import ADMIN_BASELINE
    assert 'skills:submit' in API_PERMISSIONS and 'skills:submit' in ADMIN_BASELINE.apis


def test_a_member_sees_only_their_own_submissions(database, world):
    _private(database, world, BOB)
    made = _submit(database, world)
    with database() as db:
        assert [s['id'] for s in submissions.mine(db, BOB, world.id)] == [made['id']]
        assert submissions.mine(db, CARA, world.id) == []
        from uuid import UUID
        with pytest.raises(NotFound):
            submissions.get_mine(db, CARA, world.id, UUID(made['id']))  # someone else's looks like none
        with pytest.raises(NotFound):
            submissions.withdraw(db, CARA, world.id, UUID(made['id']))


def test_a_submission_changes_nothing_published_until_approval(database, world):
    _private(database, world, BOB)
    _submit(database, world)
    with database() as db:
        assert db.scalars(select(SkillRecord).where(SkillRecord.owner_user_id.is_(None))).all() == []


def test_approval_publishes_a_library_skill_that_remembers_its_author_and_reviewer(database, world):
    from uuid import UUID
    bob = _private(database, world, BOB, files={'refs/a.md': 'one'})
    made = _submit(database, world)
    with database() as db:
        shown = submissions.detail(db, PRINCIPAL, world.id, UUID(made['id']))
        assert shown['skill_md'] == MD and shown['files'] == {'refs/a.md': 'one'}
        assert '+++ submission/SKILL.md' in shown['diff'] and shown['library_moved'] is False
        assert 'every agent' in shown['notice']
    with database() as db:
        approved = submissions.approve(db, PRINCIPAL, world.id, UUID(made['id']))
    assert approved['state'] == 'approved' and approved['version'] == 1
    with database() as db:
        library = db.scalar(select(SkillRecord).where(SkillRecord.owner_user_id.is_(None)))
        version = db.get(SkillVersionRecord, library.current_version_id)
        assert library.source == 'user' and version.trust == 'user' and version.created_by == bob
        assert version.extra['origin']['submission_id'] == made['id'] and version.extra['origin']['kind'] == 'submission'
        row = db.get(SkillSubmissionRecord, UUID(made['id']))
        assert row.published_version_id == version.id and row.reviewed_by is not None
        actions = {a.action for a in db.scalars(select(AuditRecord))}
        assert {'skill.submitted', 'skill.submission_approved', 'skill.published'} <= actions
    with database() as db, pytest.raises(Conflict, match='skill_submission_not_pending'):
        submissions.approve(db, PRINCIPAL, world.id, UUID(made['id']))


def test_only_administrators_review(database, world):
    from uuid import UUID
    _private(database, world, BOB)
    made = _submit(database, world)
    for method, args in ((submissions.queue, ()), (submissions.detail, (UUID(made['id']),)),
                         (submissions.approve, (UUID(made['id']),)), (submissions.reject, (UUID(made['id']), 'no'))):
        with database() as db, pytest.raises(Forbidden):
            method(db, BOB, world.id, *args)


def test_rejection_needs_a_reason_and_is_shown_to_the_submitter(database, world):
    from uuid import UUID
    _private(database, world, BOB)
    made = _submit(database, world)
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_submission_reason_required'):
        submissions.reject(db, PRINCIPAL, world.id, UUID(made['id']), '  ')
    with database() as db:
        submissions.reject(db, PRINCIPAL, world.id, UUID(made['id']), 'Overlaps with an existing skill')
    with database() as db:
        seen = submissions.get_mine(db, BOB, world.id, UUID(made['id']))
        assert seen['state'] == 'rejected' and seen['review_reason'] == 'Overlaps with an existing skill'
        assert submissions.queue(db, PRINCIPAL, world.id) == []


def test_withdrawing_and_resubmitting_supersedes_the_older_request(database, world):
    from uuid import UUID
    _private(database, world, BOB)
    first = _submit(database, world)
    second = _submit(database, world)
    with database() as db:
        states = {s['id']: s['state'] for s in submissions.mine(db, BOB, world.id)}
        assert states[first['id']] == 'superseded' and states[second['id']] == 'pending'
        assert submissions.withdraw(db, BOB, world.id, UUID(second['id']))['state'] == 'withdrawn'
    with database() as db, pytest.raises(Conflict):
        submissions.withdraw(db, BOB, world.id, UUID(second['id']))


def test_dangerous_content_is_refused_when_submitting_and_when_approving(database, world, monkeypatch):
    from uuid import UUID
    monkeypatch.setattr('nexus_platform.skills.service.sandbox_can_build', lambda db, profile: True)
    _private(database, world, BOB)
    made = _submit(database, world)
    # The scanner gets stricter after the submission: approval scans again and refuses.
    import nexus_platform.skills.service as service
    real = service.scan_skill

    def stricter(skill_md, files):
        result = real(skill_md, files)
        return type(result)(version=result.version, verdict='dangerous', findings=result.findings, truncated=False) \
            if hasattr(result, 'findings') else result
    monkeypatch.setattr(service, 'scan_skill', stricter)
    with database() as db, pytest.raises(SkillScanBlocked) as stopped:
        submissions.approve(db, PRINCIPAL, world.id, UUID(made['id']))
    assert stopped.value.code == 'skill_scan_refused'
    with database() as db:
        assert db.scalar(select(SkillRecord).where(SkillRecord.owner_user_id.is_(None))) is None


def test_a_moved_library_makes_the_submission_stale(database, world):
    from uuid import UUID
    _private(database, world, BOB)
    made = _submit(database, world)
    # An earlier approved submission by someone else lands first and changes the library under the same name.
    other = _private(database, world, PRINCIPAL, md=MD.replace('Write short notes', 'Write long notes'))
    second = _submit(database, world, PRINCIPAL)
    with database() as db:
        submissions.approve(db, PRINCIPAL, world.id, UUID(second['id']))
    with database() as db, pytest.raises(Conflict, match='skill_base_changed'):
        submissions.approve(db, PRINCIPAL, world.id, UUID(made['id']))
    with database() as db:
        assert db.get(SkillSubmissionRecord, UUID(made['id'])).state == 'superseded'


def test_names_held_by_builtin_or_admin_published_library_skills_are_not_open_to_submissions(database, world):
    _private(database, world, BOB)
    with database() as db:
        publish(db, PRINCIPAL, world.id, MD.replace('Write short', 'Other'), {})  # an administrator's own skill
    with database() as db, pytest.raises(InvalidConfiguration, match='skill_name_taken_by_library'):
        submissions.submit(db, BOB, world.id, 'my-notes')


def test_limits_on_the_queue(database, world, monkeypatch):
    monkeypatch.setattr(submissions, 'PER_USER_PER_HOUR', 2)
    for name in ('one', 'two', 'three'):
        _private(database, world, BOB, md=MD.replace('my-notes', name))
    _submit(database, world, name='one')
    _submit(database, world, name='two')
    with pytest.raises(Conflict, match='skill_submission_rate_limit'):
        _submit(database, world, name='three')
    monkeypatch.setattr(submissions, 'PER_USER_PER_HOUR', 99)
    monkeypatch.setattr(submissions, 'PENDING_PER_USER', 2)
    with pytest.raises(Conflict, match='skill_submission_user_limit'):
        _submit(database, world, name='three')
    monkeypatch.setattr(submissions, 'PENDING_PER_USER', 99)
    monkeypatch.setattr(submissions, 'PENDING_TOTAL', 2)
    with pytest.raises(Conflict, match='skill_submission_queue_full'):
        _submit(database, world, name='three')


def test_an_administrator_shares_a_private_skill_straight_into_the_library(database, world):
    _private(database, world, PRINCIPAL)
    with database() as db:
        shared = submissions.share(db, PRINCIPAL, world.id, 'my-notes')
    assert shared['version'] == 1
    with database() as db:
        library = db.scalar(select(SkillRecord).where(SkillRecord.owner_user_id.is_(None)))
        assert library.source == 'admin'
        assert db.scalar(select(SkillRecord).where(SkillRecord.owner_user_id.is_not(None))) is not None  # the copy is independent
    with database() as db, pytest.raises(Forbidden):
        submissions.share(db, BOB, world.id, 'my-notes')


def test_submissions_over_http(database, world):
    _private(database, world, BOB)
    base = f'/api/v1/tenants/{world.id}'
    member = _client(database, BOB)
    made = member.post(base + '/skill-submissions', json={'from_private': 'my-notes'})
    assert made.status_code == 201
    sid = made.json()['id']
    assert member.get(base + '/skill-submissions?mine=true').json()[0]['id'] == sid
    assert member.get(base + '/skill-submissions').status_code == 403  # the queue is for administrators
    assert member.get(f'{base}/skill-submissions/{sid}/review').status_code == 403
    cara = _client(database, CARA)
    assert cara.get(f'{base}/skill-submissions/{sid}').status_code == 404
    admin = _client(database, PRINCIPAL)
    assert [s['id'] for s in admin.get(base + '/skill-submissions').json()] == [sid]
    assert 'Write short notes' in admin.get(f'{base}/skill-submissions/{sid}/review').json()['skill_md']
    assert admin.post(f'{base}/skill-submissions/{sid}/reject', json={'reason': ''}).status_code == 422
    assert admin.post(f'{base}/skill-submissions/{sid}/approve').json()['state'] == 'approved'
    assert [row['name'] for row in admin.get(base + '/skills').json()] == ['my-notes']
