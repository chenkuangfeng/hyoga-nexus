"""Private skills and drafts (openspec 2026-11-07-skill-evolution, S4 4.1).

``skills.owner_user_id`` marks a private skill; the single (tenant, name) uniqueness becomes two partial indexes so
library names stay unique per space and private names unique per owner. ``skill_drafts`` holds the editable drafts.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('skills') as batch:
        batch.drop_constraint('uq_skills_tenant_name', type_='unique')
        batch.add_column(sa.Column('owner_user_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key('fk_skills_owner_user', 'users', ['owner_user_id'], ['id'], ondelete='CASCADE')
    op.create_index('uq_skills_library_name', 'skills', ['tenant_id', 'name'], unique=True,
                    sqlite_where=sa.text('owner_user_id IS NULL'), postgresql_where=sa.text('owner_user_id IS NULL'))
    op.create_index('uq_skills_private_name', 'skills', ['tenant_id', 'owner_user_id', 'name'], unique=True,
                    sqlite_where=sa.text('owner_user_id IS NOT NULL'),
                    postgresql_where=sa.text('owner_user_id IS NOT NULL'))
    op.create_table(
        'skill_drafts',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('name', sa.String(64), primary_key=True),
        sa.Column('skill_md', sa.Text(), nullable=False),
        sa.Column('files', sa.JSON(), nullable=False),
        sa.Column('base_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))


def downgrade() -> None:
    op.drop_table('skill_drafts')
    op.drop_index('uq_skills_private_name', table_name='skills')
    op.drop_index('uq_skills_library_name', table_name='skills')
    # Private skills cannot exist under the old single uniqueness; drop them before restoring it.
    op.execute('DELETE FROM skill_versions WHERE skill_id IN (SELECT id FROM skills WHERE owner_user_id IS NOT NULL)')
    op.execute('DELETE FROM skills WHERE owner_user_id IS NOT NULL')
    with op.batch_alter_table('skills') as batch:
        batch.drop_constraint('fk_skills_owner_user', type_='foreignkey')
        batch.drop_column('archived_at')
        batch.drop_column('owner_user_id')
        batch.create_unique_constraint('uq_skills_tenant_name', ['tenant_id', 'name'])
