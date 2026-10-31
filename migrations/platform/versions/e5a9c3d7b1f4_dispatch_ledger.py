"""Dispatch ledger: process epoch singleton and per-session admission FIFO."""
from alembic import op
import sqlalchemy as sa

revision = 'e5a9c3d7b1f4'
down_revision = 'c4e8a2f6d1b9'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'runtime_epoch',
        sa.Column('singleton', sa.Integer(), primary_key=True),
        sa.Column('epoch', sa.Integer(), nullable=False),
        sa.Column('instance_id', sa.String(160), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('singleton = 1', name='ck_runtime_epoch_singleton'),
    )
    op.create_table(
        'session_admissions',
        sa.Column('seq', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('admission_id', sa.Uuid(as_uuid=True), nullable=False, unique=True),
        sa.Column('session_id', sa.Uuid(as_uuid=True), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', sa.Uuid(as_uuid=True), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('owner_epoch', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'started', 'unknown', 'terminal')", name='ck_session_admissions_status'),
    )
    op.create_index('ix_session_admissions_session_status', 'session_admissions', ['session_id', 'status'])


def downgrade():
    op.drop_index('ix_session_admissions_session_status', table_name='session_admissions')
    op.drop_table('session_admissions')
    op.drop_table('runtime_epoch')
