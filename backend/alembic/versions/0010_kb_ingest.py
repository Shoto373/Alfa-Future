"""kb ingest: uploaded PDFs and thesis drafts

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    # Конвейер аналитики банка (SPR3-03): PDF на распознавание и черновики тезисов до проверки аналитиком.
    op.create_table(
        'kb_uploads',
        sa.Column('doc_id', sa.Text(), nullable=False),
        sa.Column('filename', sa.Text(), nullable=False),
        sa.Column('sha256', sa.Text(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('status', sa.Text(), server_default='queued', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'processing', 'ready', 'failed')", name='kb_uploads_status_check'),
        sa.PrimaryKeyConstraint('doc_id'),
        sa.UniqueConstraint('sha256'),
    )
    op.create_table(
        'thesis_drafts',
        sa.Column('draft_id', sa.Text(), nullable=False),
        sa.Column('doc_id', sa.Text(), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('status', sa.Text(), server_default='draft', nullable=False),
        sa.Column('thesis_id', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.Text(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'approved', 'rejected')", name='thesis_drafts_status_check'),
        sa.ForeignKeyConstraint(['doc_id'], ['kb_uploads.doc_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('draft_id'),
    )
    op.create_index('thesis_drafts_doc_idx', 'thesis_drafts', ['doc_id', 'page'])


def downgrade():
    op.drop_index('thesis_drafts_doc_idx', table_name='thesis_drafts')
    op.drop_table('thesis_drafts')
    op.drop_table('kb_uploads')
