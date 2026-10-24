"""subscriptions and deliveries (digest and alerts)

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    # Проактивность (SPR4-04): подписки пользователей и журнал доставки сводок и алертов.
    op.create_table(
        'subscriptions',
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=False),
        sa.Column('unsubscribe_token', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'company_id'),
        sa.UniqueConstraint('unsubscribe_token'),
    )
    op.create_table(
        'deliveries',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('channel', sa.Text(), nullable=False),
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default='queued', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'sent', 'failed', 'skipped')", name='deliveries_status_check'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', 'channel', name='deliveries_key_channel_uq'),
    )
    op.create_index('deliveries_user_idx', 'deliveries', ['user_id', 'company_id', 'created_at'])


def downgrade():
    op.drop_index('deliveries_user_idx', table_name='deliveries')
    op.drop_table('deliveries')
    op.drop_table('subscriptions')
