"""counterparty graph edges and alerts

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    # Граф контрагентов и события у них (SPR4-01).
    op.create_table(
        'company_edges',
        sa.Column('src', sa.Text(), nullable=False),
        sa.Column('dst', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('share_out', sa.Numeric(), nullable=False),
        sa.Column('share_in', sa.Numeric(), nullable=True),
        sa.Column('amount', sa.Numeric(), server_default='0', nullable=False),
        sa.Column('count', sa.Integer(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('src', 'dst', 'kind'),
    )
    op.create_index('company_edges_dst_idx', 'company_edges', ['dst'])
    op.create_table(
        'counterparty_alerts',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=False),
        sa.Column('news_id', sa.Text(), nullable=False),
        sa.Column('counterparty_id', sa.Text(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'news_id', 'counterparty_id', name='counterparty_alerts_uq'),
    )
    op.create_index('counterparty_alerts_company_idx', 'counterparty_alerts', ['company_id', 'created_at'])


def downgrade():
    op.drop_index('counterparty_alerts_company_idx', table_name='counterparty_alerts')
    op.drop_table('counterparty_alerts')
    op.drop_index('company_edges_dst_idx', table_name='company_edges')
    op.drop_table('company_edges')
