"""Knowledge enrichment (openspec 2026-11-06-knowledge-base K5.2): summaries, generated questions, enrich jobs.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('knowledge_chunks') as batch:
        batch.add_column(sa.Column('questions', sa.JSON(), server_default='[]', nullable=False))
    with op.batch_alter_table('knowledge_document_versions') as batch:
        batch.add_column(sa.Column('summary', sa.Text(), nullable=True))
        batch.add_column(sa.Column('enrichment', sa.JSON(), server_default='{}', nullable=False))
    with op.batch_alter_table('knowledge_jobs') as batch:
        batch.drop_constraint('ck_knowledge_jobs_kind', type_='check')
        batch.create_check_constraint('ck_knowledge_jobs_kind', "kind IN ('index','cleanup','enrich')")


def downgrade() -> None:
    op.execute("DELETE FROM knowledge_jobs WHERE kind = 'enrich'")
    with op.batch_alter_table('knowledge_jobs') as batch:
        batch.drop_constraint('ck_knowledge_jobs_kind', type_='check')
        batch.create_check_constraint('ck_knowledge_jobs_kind', "kind IN ('index','cleanup')")
    with op.batch_alter_table('knowledge_document_versions') as batch:
        batch.drop_column('enrichment')
        batch.drop_column('summary')
    with op.batch_alter_table('knowledge_chunks') as batch:
        batch.drop_column('questions')
