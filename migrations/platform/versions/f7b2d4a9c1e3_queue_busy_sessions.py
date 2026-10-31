"""Allow queued Runs per session; keep at most one executing Run per session."""
from alembic import op
import sqlalchemy as sa

revision = 'f7b2d4a9c1e3'
down_revision = 'e5a9c3d7b1f4'
branch_labels = depends_on = None

EXECUTING = "status IN ('running','waiting_input','waiting_approval')"
ACTIVE = "status IN ('queued','running','waiting_input','waiting_approval')"


def upgrade():
    op.drop_index('uq_runs_active_session', table_name='runs')
    op.create_index('uq_runs_active_session', 'runs', ['session_id'], unique=True,
                    sqlite_where=sa.text(EXECUTING), postgresql_where=sa.text(EXECUTING))


def downgrade():
    op.drop_index('uq_runs_active_session', table_name='runs')
    op.create_index('uq_runs_active_session', 'runs', ['session_id'], unique=True,
                    sqlite_where=sa.text(ACTIVE), postgresql_where=sa.text(ACTIVE))
