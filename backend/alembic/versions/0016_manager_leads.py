"""bank managers' clients and leads

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    # Связь с банком (SPR4-06): клиенты менеджера и заявки «обсудить с менеджером» (только с согласия).
    op.create_table(
        'manager_clients',
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('email', 'company_id'),
    )
    op.create_table(
        'leads',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('insight_id', sa.Text(), nullable=False),
        sa.Column('offer_id', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default='new', nullable=False),
        sa.Column('consent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("status IN ('new', 'in_progress', 'done', 'declined')", name='leads_status_check'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'insight_id', 'offer_id', name='leads_user_insight_offer_uq'),
    )
    op.create_index('leads_company_idx', 'leads', ['company_id', 'created_at'])


def downgrade():
    op.drop_index('leads_company_idx', table_name='leads')
    op.drop_table('leads')
    op.drop_table('manager_clients')
