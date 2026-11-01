"""Memory stage 1: screened drafts, tombstones, enable/validity flags and a SQLite keyword index.

Openspec 2026-11-01-memory-optimization (design 9.2, 9.11). Existing rows keep their meaning:
drafts default to origin 'foreground' with no fingerprint; entries default to enabled with no
validity end. Existing published versions are backfilled with tokens, a fingerprint and a stable
search id, and on SQLite they are loaded into the FTS5 index so search works on upgraded data.
"""
from alembic import op
import sqlalchemy as sa

from nexus_memory.text import fingerprint, tokenize
from nexus_platform.persistence.models.memory import keyword_index_supported

revision = 'e2b7d4a8c1f6'
down_revision = 'a6c3e9f2b1d8'
branch_labels = depends_on = None

MEMORY_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
    "tokens, content='', contentless_delete=1, tokenize='unicode61')"
)


def upgrade():
    bind = op.get_bind()
    op.add_column('memory_drafts', sa.Column('origin', sa.String(16), nullable=False,
                                             server_default='foreground'))
    op.add_column('memory_drafts', sa.Column('fingerprint', sa.String(64), nullable=True))
    op.add_column('memory_drafts', sa.Column('base_version', sa.Integer(), nullable=True))
    op.add_column('memory_drafts', sa.Column('source_message_ids', sa.JSON(), nullable=True))
    op.create_index('ix_memory_drafts_fingerprint', 'memory_drafts', ['tenant_id', 'fingerprint'])

    op.add_column('memory_versions', sa.Column('fingerprint', sa.String(64), nullable=True))
    op.add_column('memory_versions', sa.Column('tokens', sa.Text(), nullable=True))
    op.add_column('memory_versions', sa.Column('search_id', sa.Integer(), nullable=True))
    op.add_column('memory_versions', sa.Column('source_message_ids', sa.JSON(), nullable=True))

    op.add_column('memory_entries', sa.Column('enabled', sa.Boolean(), nullable=False,
                                              server_default=sa.true()))
    op.add_column('memory_entries', sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True))

    op.create_table('memory_tombstones',
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('owner_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('fingerprint', sa.String(64), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))

    # Backfill published versions so that existing content is searchable and deduplicated.
    rows = bind.execute(sa.text('SELECT entry_id, version, content FROM memory_versions ORDER BY created_at, version')).fetchall()
    for number, (entry_id, version, content) in enumerate(rows, start=1):
        bind.execute(sa.text(
            'UPDATE memory_versions SET fingerprint = :fp, tokens = :tk, search_id = :sid '
            'WHERE entry_id = :e AND version = :v'),
            {'fp': fingerprint(content), 'tk': tokenize(content), 'sid': number, 'e': entry_id, 'v': version})
    op.create_index('uq_memory_versions_search_id', 'memory_versions', ['search_id'], unique=True)

    if bind.dialect.name == 'sqlite' and keyword_index_supported(bind):
        op.execute(MEMORY_FTS_DDL)
        for number, (entry_id, version, content) in enumerate(rows, start=1):
            bind.execute(sa.text('INSERT INTO memory_fts(rowid, tokens) VALUES (:sid, :tk)'),
                         {'sid': number, 'tk': tokenize(content)})


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        op.execute('DROP TABLE IF EXISTS memory_fts')
    op.drop_table('memory_tombstones')
    op.drop_index('uq_memory_versions_search_id', table_name='memory_versions')
    op.drop_column('memory_entries', 'valid_until')
    op.drop_column('memory_entries', 'enabled')
    op.drop_column('memory_versions', 'source_message_ids')
    op.drop_column('memory_versions', 'search_id')
    op.drop_column('memory_versions', 'tokens')
    op.drop_column('memory_versions', 'fingerprint')
    op.drop_index('ix_memory_drafts_fingerprint', table_name='memory_drafts')
    op.drop_column('memory_drafts', 'source_message_ids')
    op.drop_column('memory_drafts', 'base_version')
    op.drop_column('memory_drafts', 'fingerprint')
    op.drop_column('memory_drafts', 'origin')
