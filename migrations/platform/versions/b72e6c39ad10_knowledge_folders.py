"""Persist document folders and scope active document names to a folder."""
from alembic import op
import sqlalchemy as sa

revision = 'b72e6c39ad10'
down_revision = 'a03b51d982ef'
branch_labels = None
depends_on = None


def _create_name_index(*columns: str) -> None:
    active = sa.text("status = 'active'")
    op.create_index('uq_knowledge_documents_name', 'knowledge_documents', list(columns), unique=True,
                    sqlite_where=active, postgresql_where=active)


def upgrade() -> None:
    op.create_table('knowledge_folders',
                    sa.Column('kb_id', sa.Uuid(), sa.ForeignKey('knowledge_bases.id', ondelete='CASCADE'),
                              primary_key=True),
                    sa.Column('path', sa.String(1024), primary_key=True))
    op.drop_index('uq_knowledge_documents_name', table_name='knowledge_documents')
    _create_name_index('kb_id', 'folder_path', 'filename')


def downgrade() -> None:
    documents = sa.table('knowledge_documents', sa.column('kb_id'), sa.column('filename'), sa.column('status'))
    duplicates = sa.select(documents.c.kb_id).where(documents.c.status == 'active').group_by(
        documents.c.kb_id, documents.c.filename).having(sa.func.count() > 1).limit(1)
    if op.get_bind().execute(duplicates).first() is not None:
        raise RuntimeError('Remove duplicate document names across folders before downgrading')
    op.drop_index('uq_knowledge_documents_name', table_name='knowledge_documents')
    _create_name_index('kb_id', 'filename')
    op.drop_table('knowledge_folders')
