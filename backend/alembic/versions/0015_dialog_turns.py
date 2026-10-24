"""dialog turns (conversation with an insight)

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    # Диалог с разбором (SPR4-05): история реплик пользователя по разбору и оценка ответа.
    op.create_table(
        'dialog_turns',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('insight_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint('rating IN (-1, 1)', name='dialog_turns_rating_check'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('dialog_turns_insight_idx', 'dialog_turns', ['insight_id', 'user_id', 'id'])


def downgrade():
    op.drop_index('dialog_turns_insight_idx', table_name='dialog_turns')
    op.drop_table('dialog_turns')
