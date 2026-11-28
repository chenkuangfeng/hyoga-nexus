"""Persist Native model request snapshots for the trajectory inspector.

Revision ID: f2c4a6b8d0e1
Revises: b72e6c39ad10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2c4a6b8d0e1'
down_revision: Union[str, None] = 'b72e6c39ad10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('run_trajectory_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('turn', sa.Integer(), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('purpose', sa.String(length=24), nullable=False, server_default='assistant'),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='running'),
        sa.Column('input_estimate_tokens', sa.Integer(), nullable=False),
        sa.Column('run_total_tokens', sa.Integer(), nullable=True),
        sa.Column('request_snapshot', sa.JSON(), nullable=False),
        sa.Column('response_snapshot', sa.JSON(), nullable=False),
        sa.Column('usage', sa.JSON(), nullable=False),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', 'sequence', name='uq_run_trajectory_sequence'))
def downgrade() -> None:
    op.drop_table('run_trajectory_records')
