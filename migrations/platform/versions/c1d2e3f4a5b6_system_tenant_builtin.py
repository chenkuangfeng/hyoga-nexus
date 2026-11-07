"""System space, builtin resources and skill trust (openspec 2026-11-07-skill-evolution, S1).

Revision ID: c1d2e3f4a5b6
Revises: e8f9a0b1c2d3

The system space and its reserved user are created idempotently at startup (``nexus_platform.system``), not here,
so a database built from the models and one built from migrations behave the same.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tenants') as batch:
        batch.drop_constraint('ck_tenants_kind', type_='check')
        batch.create_check_constraint('ck_tenants_kind', "kind IN ('personal', 'enterprise', 'system')")
    op.create_table('tenant_builtin_disabled',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('kind', sa.String(64), primary_key=True),
        sa.Column('resource_id', sa.String(255), primary_key=True),
        sa.Column('disabled_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=False))
    with op.batch_alter_table('skill_versions') as batch:
        batch.add_column(sa.Column('trust', sa.String(16), nullable=False, server_default='admin'))
        batch.add_column(sa.Column('scan_version', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('scan', sa.JSON(), nullable=False, server_default='{}'))
        batch.add_column(sa.Column('extra', sa.JSON(), nullable=False, server_default='{}'))
    op.execute("UPDATE skills SET source = 'admin' WHERE source = 'installed'")
    op.execute("UPDATE skill_versions SET trust = 'builtin' WHERE skill_id IN (SELECT id FROM skills WHERE source = 'builtin')")


def downgrade() -> None:
    with op.batch_alter_table('skill_versions') as batch:
        batch.drop_column('extra')
        batch.drop_column('scan')
        batch.drop_column('scan_version')
        batch.drop_column('trust')
    op.drop_table('tenant_builtin_disabled')
    op.execute("UPDATE skills SET source = 'installed' WHERE source = 'admin'")
    # The system space and its resources, if any were created, must go before the narrower constraint returns.
    op.execute("DELETE FROM tenants WHERE kind = 'system'")
    with op.batch_alter_table('tenants') as batch:
        batch.drop_constraint('ck_tenants_kind', type_='check')
        batch.create_check_constraint('ck_tenants_kind', "kind IN ('personal', 'enterprise')")
