"""Local password credentials, server-side login sessions and one-time login states."""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8a2f6d1b9'
down_revision = 'b7d1e5c3a9f2'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'local_credentials',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'auth_sessions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('identity_id', sa.Uuid(), sa.ForeignKey('user_identities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_table(
        'auth_states',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('purpose', sa.String(16), nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table('auth_states')
    op.drop_index('ix_auth_sessions_user_id', table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_table('local_credentials')
