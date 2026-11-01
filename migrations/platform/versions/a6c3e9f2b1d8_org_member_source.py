"""Organization-sourced memberships and organization node snapshot on sessions.

Openspec 2026-11-01-org-agent-sharing. Existing memberships are all manual joins, so the default
keeps their meaning. Existing sessions get a null organization node.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a6c3e9f2b1d8'
down_revision = 'd1f5b8c2a9e4'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('tenant_memberships') as batch:
        batch.add_column(sa.Column('source', sa.String(16), nullable=False, server_default='manual'))
        batch.create_check_constraint('ck_membership_source', "source IN ('manual', 'organization')")
    with op.batch_alter_table('sessions') as batch:
        batch.add_column(sa.Column('org_unit_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key('fk_sessions_org_unit_id', 'org_units', ['org_unit_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('sessions') as batch:
        batch.drop_constraint('fk_sessions_org_unit_id', type_='foreignkey')
        batch.drop_column('org_unit_id')
    with op.batch_alter_table('tenant_memberships') as batch:
        batch.drop_constraint('ck_membership_source', type_='check')
        batch.drop_column('source')
