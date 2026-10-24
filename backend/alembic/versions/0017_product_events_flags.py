"""product analytics events and feature flags

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    # Продуктовая аналитика (SPR4-07): события воронки без персональных данных и фичефлаги с экспериментами.
    op.create_table(
        'product_events',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('user_hash', sa.Text(), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=True),
        sa.Column('role', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('product_events_kind_idx', 'product_events', ['kind', 'created_at'])
    op.create_index('product_events_user_idx', 'product_events', ['user_hash', 'created_at'])
    op.create_table(
        'feature_flags',
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade():
    op.drop_table('feature_flags')
    op.drop_index('product_events_user_idx', table_name='product_events')
    op.drop_index('product_events_kind_idx', table_name='product_events')
    op.drop_table('product_events')
