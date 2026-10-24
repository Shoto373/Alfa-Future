"""worker jobs queue and news.updated_at

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    # Очередь задач воркера (SPR3-01): FOR UPDATE SKIP LOCKED, повтор с задержкой, dead-letter.
    op.create_table(
        'jobs',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('status', sa.Text(), server_default='queued', nullable=False),
        sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='5', nullable=False),
        sa.Column('locked_by', sa.Text(), nullable=True),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('dedupe_key', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'dead')", name='jobs_status_check'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key'),
    )
    op.create_index('jobs_ready_idx', 'jobs', ['run_at'], postgresql_where=sa.text("status = 'queued'"))
    # Дельта кэша новостей в API: подгружаются только записи, измененные после прошлой проверки.
    op.add_column('news', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.create_index('news_updated_idx', 'news', ['updated_at'])


def downgrade():
    op.drop_index('news_updated_idx', table_name='news')
    op.drop_column('news', 'updated_at')
    op.drop_index('jobs_ready_idx', table_name='jobs')
    op.drop_table('jobs')
