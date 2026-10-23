"""vector store (pgvector) and lookup indexes

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # The extension is database-wide and lives in public, next to every application schema.
    # It is not dropped on downgrade: other schemas of the same database may use it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.create_table('vector_items',
    sa.Column('collection', sa.Text(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('item_id', sa.Text(), nullable=False),
    sa.Column('text_hash', sa.Text(), nullable=False),
    sa.Column('embedding', Vector(384), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('collection', 'model', 'item_id')
    )
    op.create_index('vector_items_embedding_idx', 'vector_items', ['embedding'], unique=False,
                    postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index('insights_cache_idx', table_name='insights')
    op.create_index('insights_lookup_idx', 'insights',
                    ['company_id', 'role', 'cache_version', 'news_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('insights_news_idx', 'insights', ['news_id'], unique=False)
    op.create_index('feedback_insight_idx', 'feedback', ['insight_id'], unique=False)
    op.create_index('answers_insight_idx', 'answers', ['insight_id'], unique=False)
    op.create_index('events_kind_idx', 'events', ['kind'], unique=False)


def downgrade():
    op.drop_index('events_kind_idx', table_name='events')
    op.drop_index('answers_insight_idx', table_name='answers')
    op.drop_index('feedback_insight_idx', table_name='feedback')
    op.drop_index('insights_news_idx', table_name='insights')
    op.drop_index('insights_lookup_idx', table_name='insights')
    op.create_index('insights_cache_idx', 'insights', ['company_id', 'role', 'news_id', sa.literal_column('created_at DESC')], unique=False)
    op.drop_index('vector_items_embedding_idx', table_name='vector_items')
    op.drop_table('vector_items')
