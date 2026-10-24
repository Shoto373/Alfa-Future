"""login failures by ip

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    # Блокировка входа по паре email + адрес: чужие неверные пароли не запирают владельца аккаунта.
    op.add_column('login_failures', sa.Column('ip', sa.Text(), server_default='', nullable=False))


def downgrade():
    op.drop_column('login_failures', 'ip')
