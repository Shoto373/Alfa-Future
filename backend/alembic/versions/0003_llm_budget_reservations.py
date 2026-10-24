"""llm budget reservations

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    # Резерв идущих вызовов LLM: бюджет проверяется с учетом еще не завершенных параллельных запросов.
    op.create_table('llm_reservations',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('tokens', sa.BigInteger(), nullable=False),
    sa.Column('cost', sa.Numeric(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['day'], ['llm_usage.day'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('llm_reservations_created_idx', 'llm_reservations', ['created_at'], unique=False)
    op.add_column('llm_usage', sa.Column('reserved_tokens', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('llm_usage', sa.Column('reserved_cost', sa.Numeric(), server_default='0', nullable=False))
    op.add_column('llm_usage', sa.Column('rejected', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('llm_usage', 'rejected')
    op.drop_column('llm_usage', 'reserved_cost')
    op.drop_column('llm_usage', 'reserved_tokens')
    op.drop_index('llm_reservations_created_idx', table_name='llm_reservations')
    op.drop_table('llm_reservations')
