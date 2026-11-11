"""Department and member audiences for agents and knowledge bases (openspec 2026-11-11-enterprise-saas E5).

New tables ``agent_audiences`` and ``knowledge_base_audiences``; ``knowledge_bases.visibility`` admits ``scoped``
(readable by the listed departments and members).
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = depends_on = None


def _audience(name: str, owner: str, owner_table: str, fk_name: str, unique_name: str, check_name: str):
    op.create_table(
        name,
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column(owner, sa.Uuid(), nullable=False),
        sa.Column('principal_kind', sa.String(16), nullable=False),
        sa.Column('principal_id', sa.Uuid(), nullable=False),
        sa.Column('include_descendants', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('granted_by', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint([owner, 'tenant_id'], [f'{owner_table}.id', f'{owner_table}.tenant_id'],
                                ondelete='CASCADE', name=fk_name),
        sa.UniqueConstraint(owner, 'principal_kind', 'principal_id', name=unique_name),
        sa.CheckConstraint("principal_kind IN ('user', 'org_unit')", name=check_name),
    )


def upgrade():
    _audience('agent_audiences', 'agent_id', 'agents', 'fk_agent_audiences_agent_tenant', 'uq_agent_audiences',
              'ck_agent_audiences_kind')
    op.create_index('ix_agent_audiences_principal', 'agent_audiences', ['tenant_id', 'principal_kind', 'principal_id'])
    _audience('knowledge_base_audiences', 'kb_id', 'knowledge_bases', 'fk_kb_audiences_kb_tenant', 'uq_kb_audiences',
              'ck_kb_audiences_kind')
    with op.batch_alter_table('knowledge_bases') as batch:
        batch.drop_constraint('ck_knowledge_bases_visibility', type_='check')
        batch.create_check_constraint('ck_knowledge_bases_visibility', "visibility IN ('private','tenant','scoped')")


def downgrade():
    op.execute("UPDATE knowledge_bases SET visibility = 'private' WHERE visibility = 'scoped'")
    with op.batch_alter_table('knowledge_bases') as batch:
        batch.drop_constraint('ck_knowledge_bases_visibility', type_='check')
        batch.create_check_constraint('ck_knowledge_bases_visibility', "visibility IN ('private','tenant')")
    op.drop_table('knowledge_base_audiences')
    op.drop_index('ix_agent_audiences_principal', table_name='agent_audiences')
    op.drop_table('agent_audiences')
