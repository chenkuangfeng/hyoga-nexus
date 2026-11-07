"""Wiki knowledge bases (openspec 2026-11-06-knowledge-base K6): pages, revisions, folders, issues, wiki jobs.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT = lambda: sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
_KB = lambda: sa.Column('kb_id', sa.Uuid(), sa.ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
_TS = lambda name: sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    with op.batch_alter_table('knowledge_jobs') as batch:
        batch.drop_constraint('ck_knowledge_jobs_kind', type_='check')
        batch.create_check_constraint('ck_knowledge_jobs_kind', "kind IN ('index','cleanup','enrich','wiki')")
    op.create_table('knowledge_wiki_pages',
        sa.Column('id', sa.Uuid(), primary_key=True), _TENANT(), _KB(),
        sa.Column('slug', sa.String(200), nullable=False), sa.Column('title', sa.String(300), nullable=False),
        sa.Column('page_type', sa.String(16), nullable=False), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False), sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=False), sa.Column('folder_id', sa.Uuid(), nullable=True),
        sa.Column('category_path', sa.JSON(), nullable=False), sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('source_refs', sa.JSON(), nullable=False), sa.Column('in_links', sa.JSON(), nullable=False),
        sa.Column('out_links', sa.JSON(), nullable=False), sa.Column('page_metadata', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('last_edit_source', sa.String(16), nullable=False),
        sa.Column('last_editor_id', sa.Uuid(), nullable=True), sa.Column('index_state', sa.String(16), nullable=False),
        sa.Column('index_attempts', sa.Integer(), nullable=False), sa.Column('index_error', sa.Text(), nullable=True),
        _TS('created_at'), _TS('updated_at'),
        sa.UniqueConstraint('kb_id', 'slug', name='uq_wiki_pages_slug'),
        sa.CheckConstraint("status IN ('published','draft','archived','deleting')", name='ck_wiki_pages_status'),
        sa.CheckConstraint("index_state IN ('pending','ready','failed')", name='ck_wiki_pages_index_state'))
    op.create_index('ix_wiki_pages_kb', 'knowledge_wiki_pages', ['kb_id', 'status', 'page_type'])
    op.create_index('ix_wiki_pages_pending', 'knowledge_wiki_pages', ['index_state', 'status'])
    op.create_table('knowledge_wiki_revisions',
        sa.Column('id', sa.Uuid(), primary_key=True), _TENANT(), _KB(),
        sa.Column('page_id', sa.Uuid(), sa.ForeignKey('knowledge_wiki_pages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slug', sa.String(200), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(300), nullable=False), sa.Column('page_type', sa.String(16), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('content', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False), sa.Column('aliases', sa.JSON(), nullable=False),
        sa.Column('edit_source', sa.String(16), nullable=False), sa.Column('editor_id', sa.Uuid(), nullable=True),
        _TS('edited_at'), _TS('created_at'),
        sa.UniqueConstraint('page_id', 'version', name='uq_wiki_revisions_version'))
    op.create_table('knowledge_wiki_folders',
        sa.Column('id', sa.Uuid(), primary_key=True), _TENANT(), _KB(),
        sa.Column('parent_id', sa.Uuid(), nullable=True), sa.Column('name', sa.String(120), nullable=False),
        sa.Column('path', sa.String(500), nullable=False), sa.Column('depth', sa.Integer(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False), _TS('created_at'), _TS('updated_at'),
        sa.UniqueConstraint('kb_id', 'path', name='uq_wiki_folders_path'))
    op.create_table('knowledge_wiki_issues',
        sa.Column('id', sa.Uuid(), primary_key=True), _TENANT(), _KB(),
        sa.Column('slug', sa.String(200), nullable=False), sa.Column('issue_type', sa.String(32), nullable=False),
        sa.Column('description', sa.Text(), nullable=False), sa.Column('suspected_knowledge_ids', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('reported_by', sa.String(32), nullable=False),
        _TS('created_at'), _TS('updated_at'),
        sa.CheckConstraint("status IN ('pending','resolved','ignored')", name='ck_wiki_issues_status'))
    op.create_index('ix_wiki_issues_kb', 'knowledge_wiki_issues', ['kb_id', 'status'])


def downgrade() -> None:
    op.drop_table('knowledge_wiki_issues')
    op.drop_table('knowledge_wiki_folders')
    op.drop_table('knowledge_wiki_revisions')
    op.drop_table('knowledge_wiki_pages')
    op.execute("DELETE FROM knowledge_jobs WHERE kind = 'wiki'")
    with op.batch_alter_table('knowledge_jobs') as batch:
        batch.drop_constraint('ck_knowledge_jobs_kind', type_='check')
        batch.create_check_constraint('ck_knowledge_jobs_kind', "kind IN ('index','cleanup','enrich')")
