"""Verify legacy directory inference and lossless rollback of organization link sources."""
import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_org_link_sources_upgrade_downgrade_and_reupgrade():
    path = Path(__file__).parents[1] / 'migrations/platform/versions/a03b51d982ef_org_link_sources.py'
    spec = importlib.util.spec_from_file_location('org_sources_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metadata = sa.MetaData()
    nodes = sa.Table('org_units', metadata, sa.Column('id', sa.Uuid(), primary_key=True),
                     sa.Column('external_id', sa.String()))
    members = sa.Table('wecom_members', metadata, sa.Column('tenant_id', sa.Uuid()),
                       sa.Column('user_id', sa.Uuid()), sa.Column('department_ids', sa.JSON()))
    links = sa.Table('user_org_units', metadata, sa.Column('tenant_id', sa.Uuid(), primary_key=True),
                     sa.Column('user_id', sa.Uuid(), primary_key=True), sa.Column('unit_id', sa.Uuid(), primary_key=True),
                     sa.Column('is_primary', sa.Boolean(), nullable=False))
    tenant, user, directory, local, stale = (uuid4() for _ in range(5))
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(nodes.insert(), [{'id': directory, 'external_id': '1'},
                                            {'id': local, 'external_id': None},
                                            {'id': stale, 'external_id': '2'}])
        connection.execute(members.insert(), {'tenant_id': tenant, 'user_id': user, 'department_ids': [1]})
        connection.execute(links.insert(), [{'tenant_id': tenant, 'user_id': user, 'unit_id': unit,
                                              'is_primary': unit == local} for unit in (directory, local, stale)])
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            rows = connection.execute(sa.text('SELECT unit_id, source, is_primary FROM user_org_units')).all()
            assert {row.unit_id: row.source for row in rows} == {
                directory.hex: 'wecom', local.hex: 'manual', stale.hex: 'manual'}
            assert sum(row.is_primary for row in rows) == 1
            module.downgrade()
            assert 'source' not in {col['name'] for col in sa.inspect(connection).get_columns('user_org_units')}
            assert connection.scalar(sa.text('SELECT count(*) FROM user_org_units')) == 3
            module.upgrade()
            assert connection.scalar(sa.text("SELECT count(*) FROM user_org_units WHERE source = 'wecom'")) == 1
    engine.dispose()
