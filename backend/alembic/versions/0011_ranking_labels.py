"""ranking labels for relevance evaluation

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    # Экспертная разметка релевантности (SPR3-06): оценка 0–3 пары «новость × компания × роль» от разметчика.
    op.create_table(
        'ranking_labels',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('news_id', sa.Text(), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('grade', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), server_default='', nullable=False),
        sa.Column('annotator', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('grade BETWEEN 0 AND 3', name='ranking_labels_grade_check'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('news_id', 'company_id', 'role', 'annotator', name='ranking_labels_pair_uq'),
    )


def downgrade():
    op.drop_table('ranking_labels')
