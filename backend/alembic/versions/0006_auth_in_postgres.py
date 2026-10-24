"""auth in postgres

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    # Пользователи, членство и сессии — из JSON в RUNTIME_DIR в PostgreSQL (перенос: app.legacy_import).
    op.create_table('login_failures',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('login_failures_email_at_idx', 'login_failures', ['email', 'at'], unique=False)
    op.create_table('users',
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('pw_salt', sa.Text(), nullable=False),
    sa.Column('pw_hash', sa.Text(), nullable=False),
    sa.Column('pw_params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('user_id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('memberships',
    sa.Column('member_id', sa.Text(), nullable=False),
    sa.Column('company_id', sa.Text(), nullable=False),
    sa.Column('user_id', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('is_admin', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('founder', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('invited_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('member_id'),
    sa.UniqueConstraint('company_id', 'email', name='memberships_company_email_uq')
    )
    op.create_index('memberships_user_idx', 'memberships', ['user_id'], unique=False)
    op.create_table('sessions',
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index('sessions_expires_idx', 'sessions', ['expires_at'], unique=False)
    op.create_index('sessions_user_idx', 'sessions', ['user_id'], unique=False)


def downgrade():
    # Откат удалил бы учетные записи — только для пустой базы, как у начальной ревизии.
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM users)")).scalar():
        raise RuntimeError("0006 downgrade refused: users table is not empty")
    op.drop_index('sessions_user_idx', table_name='sessions')
    op.drop_index('sessions_expires_idx', table_name='sessions')
    op.drop_table('sessions')
    op.drop_index('memberships_user_idx', table_name='memberships')
    op.drop_table('memberships')
    op.drop_table('users')
    op.drop_index('login_failures_email_at_idx', table_name='login_failures')
    op.drop_table('login_failures')
