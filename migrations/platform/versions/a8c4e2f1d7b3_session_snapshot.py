"""Session state snapshot columns: watermark (optimistic token), snapshot_version and data-only snapshot."""
from alembic import op
import sqlalchemy as sa

revision = 'a8c4e2f1d7b3'
down_revision = 'f7b2d4a9c1e3'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('sessions') as batch:
        batch.add_column(sa.Column('watermark', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('snapshot_version', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('snapshot', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('sessions') as batch:
        batch.drop_column('snapshot')
        batch.drop_column('snapshot_version')
        batch.drop_column('watermark')
