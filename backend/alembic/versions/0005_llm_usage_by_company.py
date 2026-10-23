"""llm usage by company

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    # Доля компании в общем дневном бюджете LLM: резерв и факт по компании-клиенту.
    op.create_table('llm_usage_companies',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('company_id', sa.Text(), nullable=False),
    sa.Column('tokens', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('cost', sa.Numeric(), server_default='0', nullable=False),
    sa.Column('calls', sa.Integer(), server_default='0', nullable=False),
    sa.Column('reserved_tokens', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('reserved_cost', sa.Numeric(), server_default='0', nullable=False),
    sa.Column('rejected', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['day'], ['llm_usage.day'], ),
    sa.PrimaryKeyConstraint('day', 'company_id')
    )
    op.add_column('llm_reservations', sa.Column('company_id', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('llm_reservations', 'company_id')
    op.drop_table('llm_usage_companies')
