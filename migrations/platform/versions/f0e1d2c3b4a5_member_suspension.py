"""Add reversible enterprise member suspension state."""
from alembic import op
import sqlalchemy as sa

revision = 'f0e1d2c3b4a5'
down_revision = 'd0e1f2a3b4c5'
branch_labels = depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tenant_memberships') as batch:
        batch.drop_constraint('ck_membership_status', type_='check')
        batch.create_check_constraint('ck_membership_status', "status IN ('active', 'suspended', 'revoked')")
        batch.add_column(sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE tenant_memberships SET status = 'active' WHERE status = 'suspended'"))
    with op.batch_alter_table('tenant_memberships') as batch:
        batch.drop_column('suspended_at')
        batch.drop_constraint('ck_membership_status', type_='check')
        batch.create_check_constraint('ck_membership_status', "status IN ('active', 'revoked')")
