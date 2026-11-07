"""Skill bundles and install state (openspec 2026-11-07-skill-evolution, S3 3.1).

Existing versions get ``build_state = 'ready'`` and no bundle; the zip is rebuilt from their file rows on demand.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('skill_versions') as batch:
        batch.add_column(sa.Column('bundle', sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column('bundle_sha256', sa.String(64), nullable=True))
        batch.add_column(sa.Column('build_state', sa.String(16), nullable=False, server_default='ready'))
        batch.add_column(sa.Column('build_error', sa.Text(), nullable=True))
        batch.add_column(sa.Column('build_log', sa.Text(), nullable=True))
        batch.add_column(sa.Column('build_heartbeat_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('env_ref', sa.String(200), nullable=True))
    op.create_index('uq_skill_versions_installing', 'skill_versions', ['skill_id'], unique=True,
                    sqlite_where=sa.text("build_state = 'installing'"),
                    postgresql_where=sa.text("build_state = 'installing'"))


def downgrade() -> None:
    op.drop_index('uq_skill_versions_installing', table_name='skill_versions')
    with op.batch_alter_table('skill_versions') as batch:
        for column in ('env_ref', 'build_heartbeat_at', 'build_log', 'build_error', 'build_state',
                       'bundle_sha256', 'bundle'):
            batch.drop_column(column)
