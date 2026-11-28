"""Allow truthful Run-free provenance for manual memories."""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = 'c6a1e9d4b730'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve legacy sources; only manual entries use NULL."""
    for table in ('memory_drafts', 'memory_versions'):
        with op.batch_alter_table(table) as batch:
            batch.alter_column('source_run_id', existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    """Refuse loss of manual provenance on rollback; remove manual records explicitly first."""
    for table in ('memory_drafts', 'memory_versions'):
        with op.batch_alter_table(table) as batch:
            batch.alter_column('source_run_id', existing_type=sa.Uuid(), nullable=False)
