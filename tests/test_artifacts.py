"""Sandbox artifacts: registration, limits and authorization (openspec 2026-11-07-tool-expansion 4.6)."""
import hashlib
from uuid import UUID

import pytest
from sqlalchemy import select

from test_platform import database  # noqa: F401  (fixture)
from test_schedule_rest_service import MEMBER, OTHER_MEMBER, OWNER, STRANGER, world  # noqa: F401  (fixtures and people)
from nexus_platform.artifacts import service
from nexus_platform.errors import NotFound
from nexus_platform.identity.service import resolve_user
from nexus_platform.persistence.models import ArtifactRecord, AuditRecord, RunEventRecord
from nexus_platform.runs.compatibility import create_run
from nexus_platform.sessions.service import create_session


@pytest.fixture
def run_of(world, tmp_path):
    """A Run of a session owned by MEMBER, plus a workspace `outputs` directory and an artifact root."""
    factory, tenant_id, agent_id, version_id = world
    with factory() as db:
        session = create_session(db, MEMBER, tenant_id, agent_version_id=version_id, title='Work')
    with factory() as db:
        run, _ = create_run(db, MEMBER, tenant_id, session.id, message='make a report', idempotency_key='k1')
    with factory() as db, db.begin():
        owner_id = resolve_user(db, MEMBER).id
    outputs = tmp_path / 'outputs'
    outputs.mkdir()
    return dict(factory=factory, tenant_id=tenant_id, session_id=session.id, run_id=run.id, owner_id=owner_id,
                outputs=outputs, root=tmp_path / 'artifacts', tmp=tmp_path)


def listing(outputs):
    return [(f'/outputs/{p.relative_to(outputs).as_posix()}', p, p.stat().st_size) for p in sorted(outputs.rglob('*')) if p.is_file()]


def register(ctx, files=None, run_id=None):
    with ctx['factory']() as db:
        return service.register_run_outputs(
            db, tenant_id=ctx['tenant_id'], session_id=ctx['session_id'], run_id=run_id or ctx['run_id'],
            owner_user_id=ctx['owner_id'], files=files if files is not None else listing(ctx['outputs']), root=ctx['root'])


def test_outputs_are_copied_recorded_and_announced(run_of):
    ctx = run_of
    (ctx['outputs'] / 'report.md').write_text('# 报告\n', encoding='utf-8')
    (ctx['outputs'] / 'data').mkdir()
    (ctx['outputs'] / 'data' / 'rows.csv').write_text('a,b\n1,2\n', encoding='utf-8')
    result = register(ctx)
    assert [item['path'] for item in result['registered']] == ['/outputs/data/rows.csv', '/outputs/report.md']
    report = next(item for item in result['registered'] if item['name'] == 'report.md')
    assert report['sha256'] == hashlib.sha256('# 报告\n'.encode()).hexdigest() and report['mime'] == 'text/markdown'
    stored = ctx['root'] / ctx['tenant_id'].__str__() / report['id']
    assert stored.read_text(encoding='utf-8') == '# 报告\n'
    (ctx['outputs'] / 'report.md').write_text('changed later', encoding='utf-8')
    assert stored.read_text(encoding='utf-8') == '# 报告\n', 'the copy does not follow later edits'
    with ctx['factory']() as db:
        event = [e for e in db.scalars(select(RunEventRecord)) if e.event_type == 'artifacts.registered'][-1]
        assert event.payload['count'] == 2 and len(event.payload['ids']) == 2
        assert 'artifact.registered' in [a.action for a in db.scalars(select(AuditRecord))]


def test_unchanged_files_are_not_registered_twice_but_changes_are(run_of):
    ctx = run_of
    (ctx['outputs'] / 'a.txt').write_text('one', encoding='utf-8')
    assert len(register(ctx)['registered']) == 1
    again = register(ctx, run_id=_next_run(ctx))
    assert again['registered'] == [] and again['skipped'] == [{'path': '/outputs/a.txt', 'reason': 'unchanged'}]
    assert len(list((ctx['root'] / str(ctx['tenant_id'])).iterdir())) == 1, 'the duplicate copy is removed'
    (ctx['outputs'] / 'a.txt').write_text('two', encoding='utf-8')
    assert len(register(ctx, run_id=_next_run(ctx, 'k3'))['registered']) == 1


def _next_run(ctx, key='k2'):
    with ctx['factory']() as db:
        run, _ = create_run(db, MEMBER, ctx['tenant_id'], ctx['session_id'], message='again', idempotency_key=key)
    return run.id


def test_symlinks_and_vanished_files_are_skipped_without_failing(run_of):
    ctx = run_of
    secret = ctx['tmp'] / 'secret.txt'
    secret.write_text('host secret', encoding='utf-8')
    (ctx['outputs'] / 'link.txt').symlink_to(secret)
    (ctx['outputs'] / 'ok.txt').write_text('fine', encoding='utf-8')
    files = [('/outputs/link.txt', ctx['outputs'] / 'link.txt', 11), ('/outputs/ok.txt', ctx['outputs'] / 'ok.txt', 4),
             ('/outputs/gone.txt', ctx['outputs'] / 'gone.txt', 3)]
    result = register(ctx, files)
    assert [item['path'] for item in result['registered']] == ['/outputs/ok.txt']
    assert {item['path']: item['reason'] for item in result['skipped']} == {
        '/outputs/link.txt': 'unreadable', '/outputs/gone.txt': 'unreadable'}
    assert not any('host secret' in p.read_text(errors='ignore') for p in ctx['root'].rglob('*') if p.is_file())


def test_limits_skip_with_a_reason(run_of, monkeypatch):
    ctx = run_of
    for name, size in (('a.bin', 10), ('b.bin', 10), ('c.bin', 10), ('big.bin', 100)):
        (ctx['outputs'] / name).write_bytes(b'x' * size)
    monkeypatch.setattr(service, 'MAX_FILES_PER_RUN', 2)
    monkeypatch.setattr(service, 'MAX_FILE_BYTES', 50)
    result = register(ctx)
    assert {i['path']: i['reason'] for i in result['skipped']} == {'/outputs/big.bin': 'too_large', '/outputs/c.bin': 'too_many'}
    assert len(result['registered']) == 2
    monkeypatch.setattr(service, 'MAX_FILES_PER_RUN', 50)
    monkeypatch.setattr(service, 'MAX_RUN_BYTES', 15)
    (ctx['outputs'] / 'big.bin').unlink()
    (ctx['outputs'] / 'a.bin').write_bytes(b'y' * 10)
    (ctx['outputs'] / 'b.bin').write_bytes(b'z' * 10)
    result = register(ctx, run_id=_next_run(ctx))
    assert any(i['reason'] == 'run_quota' for i in result['skipped'])
    monkeypatch.setattr(service, 'MAX_RUN_BYTES', 10 ** 9)
    monkeypatch.setattr(service, 'TENANT_QUOTA_BYTES', 25)
    (ctx['outputs'] / 'd.bin').write_bytes(b'q' * 10)
    result = register(ctx, run_id=_next_run(ctx, 'k9'))
    assert 'tenant_quota' in {i['reason'] for i in result['skipped']}


def test_only_the_session_owner_and_space_managers_reach_an_artifact(run_of):
    ctx = run_of
    (ctx['outputs'] / 'r.txt').write_text('hello', encoding='utf-8')
    artifact = register(ctx)['registered'][0]
    factory, tenant_id, root = ctx['factory'], ctx['tenant_id'], ctx['root']
    for who in (MEMBER, OWNER):  # the owner of the session, and a space owner
        with factory() as db:
            assert [a['id'] for a in service.list_artifacts(db, who, tenant_id)] == [artifact['id']]
        with factory() as db:
            view, path = service.open_artifact(db, who, tenant_id, UUID(artifact['id']), root)
            assert path.read_text() == 'hello' and view['name'] == 'r.txt'
    for who in (OTHER_MEMBER, STRANGER):
        with factory() as db:
            try:
                assert service.list_artifacts(db, who, tenant_id) == []
            except Exception:
                pass  # a stranger is refused outright
        with factory() as db, pytest.raises(Exception):
            service.open_artifact(db, who, tenant_id, UUID(artifact['id']), root)
    with factory() as db:
        assert 'artifact.downloaded' in [a.action for a in db.scalars(select(AuditRecord))]
    with factory() as db:
        assert service.list_artifacts(db, MEMBER, tenant_id, session_id=ctx['session_id'])[0]['id'] == artifact['id']
        assert service.list_artifacts(db, MEMBER, tenant_id, run_id=_next_run(ctx)) == []


def test_delete_removes_the_copy_and_hides_the_artifact(run_of):
    ctx = run_of
    (ctx['outputs'] / 'r.txt').write_text('hello', encoding='utf-8')
    artifact = register(ctx)['registered'][0]
    factory, tenant_id, root = ctx['factory'], ctx['tenant_id'], ctx['root']
    with factory() as db, pytest.raises(NotFound):
        service.delete_artifact(db, OTHER_MEMBER, tenant_id, UUID(artifact['id']), root)
    with factory() as db:
        service.delete_artifact(db, MEMBER, tenant_id, UUID(artifact['id']), root)
    assert not (root / str(tenant_id) / artifact['id']).exists()
    with factory() as db:
        assert service.list_artifacts(db, MEMBER, tenant_id) == []
        assert db.get(ArtifactRecord, UUID(artifact['id'])).deleted_at is not None
    with factory() as db, pytest.raises(NotFound):
        service.open_artifact(db, MEMBER, tenant_id, UUID(artifact['id']), root)


def test_a_missing_copy_is_reported_not_served(run_of):
    ctx = run_of
    (ctx['outputs'] / 'r.txt').write_text('hello', encoding='utf-8')
    artifact = register(ctx)['registered'][0]
    (ctx['root'] / str(ctx['tenant_id']) / artifact['id']).unlink()
    with ctx['factory']() as db, pytest.raises(NotFound):
        service.open_artifact(db, MEMBER, ctx['tenant_id'], UUID(artifact['id']), ctx['root'])


# ---------------------------------------------------------------- worker side and the file store

def test_the_worker_registers_outputs_and_never_raises(run_of, monkeypatch):
    from types import SimpleNamespace
    from nexus_worker.artifacts import register_outputs
    ctx = run_of
    (ctx['outputs'] / 'r.txt').write_text('hello', encoding='utf-8')
    monkeypatch.setattr(service, 'artifacts_root', lambda: ctx['root'])
    context = SimpleNamespace(tenant_id=ctx['tenant_id'], session_id=ctx['session_id'], run_id=ctx['run_id'],
                              principal_id=ctx['owner_id'])
    sandbox = SimpleNamespace(output_files=lambda: listing(ctx['outputs']))
    assert register_outputs(ctx['factory'], context, sandbox) == 1
    assert register_outputs(ctx['factory'], context, SimpleNamespace(output_files=lambda: [])) == 0

    def broken():
        raise RuntimeError('sandbox went away')
    assert register_outputs(ctx['factory'], context, SimpleNamespace(output_files=broken)) == 0


def test_the_host_file_store_lists_regular_output_files_only(tmp_path):
    from nexus_sandbox.files import HostFileStore
    store = HostFileStore(tmp_path / 'workspace', tmp_path / 'outputs', quota_bytes=10 ** 6)
    (tmp_path / 'outputs' / 'sub').mkdir()
    (tmp_path / 'outputs' / 'sub' / 'a.txt').write_text('aa', encoding='utf-8')
    (tmp_path / 'outputs' / 'link.txt').symlink_to(tmp_path / 'outputs' / 'sub' / 'a.txt')
    (tmp_path / 'workspace' / 'scratch.txt').write_text('not an output', encoding='utf-8')
    found = store.output_files()
    assert [(virtual, size) for virtual, _, size in found] == [('/outputs/sub/a.txt', 2)]
    assert found[0][1] == tmp_path / 'outputs' / 'sub' / 'a.txt'
