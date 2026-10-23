"""llm usage by model

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    # Учет по модели: фактическая цена за 1000 токенов для сверки с оценкой резерва бюджета.
    op.create_table('llm_usage_models',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('tokens', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('cost', sa.Numeric(), server_default='0', nullable=False),
    sa.Column('calls', sa.Integer(), server_default='0', nullable=False),
    sa.Column('errors', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['day'], ['llm_usage.day'], ),
    sa.PrimaryKeyConstraint('day', 'model')
    )


def downgrade():
    op.drop_table('llm_usage_models')
