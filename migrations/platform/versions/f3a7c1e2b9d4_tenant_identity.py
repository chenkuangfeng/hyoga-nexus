"""Rename workspaces to tenants and split users from external identities.

- workspaces -> tenants; workspace_memberships -> tenant_memberships.
- every workspace_id / source_workspace_id / target_workspace_id column -> *tenant_id.
- named indexes/constraints containing "workspace" are renamed on PostgreSQL;
  SQLite keeps its generated names (they carry no behavior).
- users keep a display name; (issuer, subject) moves to user_identities(provider,
  scope, external_id). Existing rows become identities with empty scope.
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = 'f3a7c1e2b9d4'
down_revision = 'd9e351bc2802'
branch_labels = depends_on = None

COLUMN_RENAMES = [
    ('workspace_id', 'tenant_id'),
    ('source_workspace_id', 'source_tenant_id'),
    ('target_workspace_id', 'target_tenant_id'),
]
TABLE_RENAMES = [('workspaces', 'tenants'), ('workspace_memberships', 'tenant_memberships')]


PG_RESTORE_CONSTRAINTS = """
DO $$
DECLARE r record; oldname text;
BEGIN
  FOR r IN SELECT conname, conrelid::regclass AS tbl FROM pg_constraint
           WHERE conname LIKE '%tenant%' LOOP
    oldname := replace(replace(r.conname, 'tenants', 'workspaces'), 'tenant', 'workspace');
    EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.tbl, r.conname, oldname);
  END LOOP;
  FOR r IN SELECT indexname FROM pg_indexes WHERE indexname LIKE '%tenant%' LOOP
    oldname := replace(replace(r.indexname, 'tenants', 'workspaces'), 'tenant', 'workspace');
    EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, oldname);
  END LOOP;
END $$;
"""

PG_RENAME_CONSTRAINTS = """
DO $$
DECLARE r record; newname text;
BEGIN
  FOR r IN SELECT conname, conrelid::regclass AS tbl FROM pg_constraint
           WHERE conname LIKE '%workspace%' LOOP
    newname := replace(replace(r.conname, 'workspaces', 'tenants'), 'workspace', 'tenant');
    EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.tbl, r.conname, newname);
  END LOOP;
  FOR r IN SELECT indexname FROM pg_indexes WHERE indexname LIKE '%workspace%' LOOP
    newname := replace(replace(r.indexname, 'workspaces', 'tenants'), 'workspace', 'tenant');
    EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, newname);
  END LOOP;
END $$;
"""


def _rename_column(table, old, new):
    # Plain ALTER TABLE ... RENAME COLUMN updates foreign keys in other tables that point at the
    # column. Batch mode rebuilds only the altered table on SQLite, which left dangling references
    # such as agent_draft_bindings -> platform_resources.workspace_id.
    op.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')


def _rename_tenant_columns(tables):
    for table in tables:
        cols = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}
        for old, new in COLUMN_RENAMES:
            if old in cols:
                _rename_column(table, old, new)


def _rename_sqlite_names(old_word, new_word):
    """Rename indexes and unique constraints whose names contain `old_word` on SQLite.

    SQLite cannot rename constraints in place, so unique constraints are rebuilt through batch
    mode; indexes are dropped and recreated. PostgreSQL is handled by the DO blocks above.
    """
    insp = sa.inspect(op.get_bind())
    for table in sorted(insp.get_table_names()):
        indexes = [i for i in insp.get_indexes(table) if i['name'] and old_word in i['name']]
        uniques = [u for u in insp.get_unique_constraints(table) if u['name'] and old_word in u['name']]
        for index in indexes:
            op.drop_index(index['name'], table_name=table)
        if uniques:
            with op.batch_alter_table(table, recreate='always') as batch:
                for unique in uniques:
                    batch.drop_constraint(unique['name'], type_='unique')
                for unique in uniques:
                    batch.create_unique_constraint(unique['name'].replace(old_word, new_word),
                                                   unique['column_names'])
        for index in indexes:
            op.create_index(index['name'].replace(old_word, new_word), table, index['column_names'],
                            unique=bool(index['unique']))


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for old, new in TABLE_RENAMES:
        if old in existing:
            op.rename_table(old, new)
    _rename_tenant_columns(sorted(sa.inspect(bind).get_table_names()))
    if bind.dialect.name == 'postgresql':
        op.execute(PG_RENAME_CONSTRAINTS)
    else:
        _rename_sqlite_names('workspace', 'tenant')

    op.create_table(
        'user_identities',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(128), nullable=False),
        sa.Column('scope', sa.String(128), nullable=False, server_default=''),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider', 'scope', 'external_id', name='uq_user_identities_provider_scope_external'),
    )
    op.add_column('users', sa.Column('display_name', sa.String(160)))
    users = sa.table('users', sa.column('id', sa.Uuid()), sa.column('issuer', sa.String()),
                     sa.column('subject', sa.String()), sa.column('display_name', sa.String()),
                     sa.column('created_at', sa.DateTime(timezone=True)))
    identities = sa.table('user_identities', sa.column('id', sa.Uuid()), sa.column('user_id', sa.Uuid()),
                          sa.column('provider', sa.String()), sa.column('scope', sa.String()),
                          sa.column('external_id', sa.String()), sa.column('created_at', sa.DateTime(timezone=True)))
    rows = bind.execute(sa.select(users.c.id, users.c.issuer, users.c.subject, users.c.created_at)).fetchall()
    for row in rows:
        bind.execute(identities.insert().values(id=uuid4(), user_id=row.id, provider=row.issuer, scope='',
                                                external_id=row.subject, created_at=row.created_at))
        bind.execute(users.update().where(users.c.id == row.id).values(display_name=row.subject))
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('uq_users_issuer_subject', type_='unique')
        batch.drop_column('issuer')
        batch.drop_column('subject')


def downgrade():
    bind = op.get_bind()
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('issuer', sa.String(128)))
        batch.add_column(sa.Column('subject', sa.String(255)))
    users = sa.table('users', sa.column('id', sa.Uuid()), sa.column('issuer', sa.String()),
                     sa.column('subject', sa.String()))
    identities = sa.table('user_identities', sa.column('user_id', sa.Uuid()), sa.column('provider', sa.String()),
                          sa.column('scope', sa.String()), sa.column('external_id', sa.String()))
    for row in bind.execute(sa.select(identities.c.user_id, identities.c.provider, identities.c.external_id)
                            .where(identities.c.scope == '')).fetchall():
        bind.execute(users.update().where(users.c.id == row.user_id).values(issuer=row.provider, subject=row.external_id))
    op.execute("UPDATE users SET issuer = 'unknown', subject = CAST(id AS VARCHAR) WHERE issuer IS NULL")
    with op.batch_alter_table('users') as batch:
        batch.alter_column('issuer', nullable=False)
        batch.alter_column('subject', nullable=False)
        batch.create_unique_constraint('uq_users_issuer_subject', ['issuer', 'subject'])
        batch.drop_column('display_name')
    op.drop_table('user_identities')
    if bind.dialect.name == 'postgresql':
        op.execute(PG_RESTORE_CONSTRAINTS)
    for old, new in reversed(TABLE_RENAMES):
        present = set(sa.inspect(bind).get_table_names())
        if new in present and old not in present:
            op.rename_table(new, old)
    tables = sorted(sa.inspect(bind).get_table_names())
    for table in tables:
        cols = {c['name'] for c in sa.inspect(bind).get_columns(table)}
        for old, new in COLUMN_RENAMES:
            if new in cols:
                _rename_column(table, new, old)
    if bind.dialect.name != 'postgresql':
        _rename_sqlite_names('tenant', 'workspace')
