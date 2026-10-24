"""domain config versions (sectors, topics and actions as data)

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    # Отрасли, темы и действия как данные (SPR4-00): версии, опубликованные аналитиком без деплоя.
    op.create_table(
        'domain_config_versions',
        sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column('status', sa.Text(), server_default='published', nullable=False),
        sa.Column('created_by', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), server_default='', nullable=False),
        sa.Column('signature', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("status IN ('published', 'archived')", name='domain_config_versions_status_check'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('domain_config_versions')
