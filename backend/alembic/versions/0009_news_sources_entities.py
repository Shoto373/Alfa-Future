"""news story_id in PostgreSQL and news_entities

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    # Сюжеты хранятся в базе (SPR3-02): повторный сбор и перезапуск не пересчитывают и не дробят их.
    op.add_column('news', sa.Column('story_id', sa.Text(), nullable=True))
    op.create_index('news_story_idx', 'news', ['story_id'])
    # Организации в новостях: основа «упоминается ваша компания» и мониторинга контрагентов.
    op.create_table(
        'news_entities',
        sa.Column('news_id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('company_id', sa.Text(), nullable=True),
        sa.Column('method', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['news_id'], ['news.news_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('news_id', 'name'),
    )
    op.create_index('news_entities_company_idx', 'news_entities', ['company_id'])


def downgrade():
    op.drop_index('news_entities_company_idx', table_name='news_entities')
    op.drop_table('news_entities')
    op.drop_index('news_story_idx', table_name='news')
    op.drop_column('news', 'story_id')
