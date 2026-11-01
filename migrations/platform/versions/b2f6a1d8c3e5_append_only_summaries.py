"""Append-only context summaries with supersession links (openspec 2026-11-01-context-token-performance, P11).

Each compaction inserts a row; nothing is overwritten. The effective summary of a session is the row with the
largest `through_sequence` that no other row supersedes. `supersedes_id` is intentionally not a foreign key:
a self-referencing key would complicate the table rebuild on SQLite, and the application enforces the chain.

Existing one-row-per-session data is preserved: each row becomes the first version, with its id equal to the
session id (unique because the old primary key was the session id).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2f6a1d8c3e5'
down_revision = 'a8c4e2f1d7b3'
branch_labels = depends_on = None


def upgrade():
    op.create_table('context_summaries_next',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('source_run_id', sa.Uuid(), sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('through_sequence', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('supersedes_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.execute(
        "INSERT INTO context_summaries_next (id, session_id, tenant_id, source_run_id, through_sequence, content, supersedes_id, created_at) "
        "SELECT session_id, session_id, tenant_id, source_run_id, through_sequence, content, NULL, CURRENT_TIMESTAMP "
        "FROM context_summaries")
    op.drop_table('context_summaries')
    op.rename_table('context_summaries_next', 'context_summaries')
    op.create_index('ix_context_summaries_session_through', 'context_summaries', ['session_id', 'through_sequence'])


def downgrade():
    # Keep only the effective summary per session: the newest row that nothing supersedes.
    op.create_table('context_summaries_prev',
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('sessions.id'), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('source_run_id', sa.Uuid(), sa.ForeignKey('runs.id'), nullable=False),
        sa.Column('through_sequence', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False))
    op.execute(
        "INSERT INTO context_summaries_prev (session_id, tenant_id, source_run_id, through_sequence, content) "
        "SELECT c.session_id, c.tenant_id, c.source_run_id, c.through_sequence, c.content FROM context_summaries c "
        "WHERE c.id NOT IN (SELECT s.supersedes_id FROM context_summaries s WHERE s.supersedes_id IS NOT NULL) "
        "AND c.through_sequence = (SELECT MAX(d.through_sequence) FROM context_summaries d "
        "WHERE d.session_id = c.session_id AND d.id NOT IN (SELECT e.supersedes_id FROM context_summaries e WHERE e.supersedes_id IS NOT NULL))")
    op.drop_index('ix_context_summaries_session_through', table_name='context_summaries')
    op.drop_table('context_summaries')
    op.rename_table('context_summaries_prev', 'context_summaries')
