"""initial_schema

Revision ID: 0001
Revises: 
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None



# Immutable snapshot of the prototype schema, used only for its one-time adoption.
LEGACY_CHECKSUM = "cdb77ddf518f0a2cb06d65d6da4366f3a32ca5da05da40d029c42bbda006e2b6"
EXPECTED = {'answers': {'columns': {'created_at': ('TIMESTAMP WITH TIME ZONE', False),
                         'id': ('BIGINT', False),
                         'insight_id': ('TEXT', False),
                         'payload': ('JSONB', False)},
             'fks': [('insight_id', 'insights', 'insight_id')],
             'indexes': [],
             'pk': ['id']},
 'app_state': {'columns': {'key': ('TEXT', False),
                           'payload': ('JSONB', False),
                           'updated_at': ('TIMESTAMP WITH TIME ZONE', False)},
               'fks': [],
               'indexes': [],
               'pk': ['key']},
 'bank_documents': {'columns': {'doc_id': ('TEXT', False), 'payload': ('JSONB', False)},
                    'fks': [],
                    'indexes': [],
                    'pk': ['doc_id']},
 'bank_products': {'columns': {'payload': ('JSONB', False), 'product_id': ('TEXT', False)},
                   'fks': [],
                   'indexes': [],
                   'pk': ['product_id']},
 'bank_theses': {'columns': {'doc_id': ('TEXT', False),
                             'page': ('INTEGER', False),
                             'payload': ('JSONB', False),
                             'thesis_id': ('TEXT', False)},
                 'fks': [('doc_id', 'bank_documents', 'doc_id')],
                 'indexes': [],
                 'pk': ['thesis_id']},
 'companies': {'columns': {'company_id': ('TEXT', False),
                           'payload': ('JSONB', False),
                           'revenue': ('NUMERIC', True),
                           'sector': ('TEXT', False)},
               'fks': [],
               'indexes': ['companies_sector_idx'],
               'pk': ['company_id']},
 'events': {'columns': {'created_at': ('TIMESTAMP WITH TIME ZONE', False),
                        'id': ('BIGINT', False),
                        'kind': ('TEXT', False),
                        'payload': ('JSONB', False)},
            'fks': [],
            'indexes': [],
            'pk': ['id']},
 'feedback': {'columns': {'created_at': ('TIMESTAMP WITH TIME ZONE', False),
                          'id': ('BIGINT', False),
                          'insight_id': ('TEXT', False),
                          'payload': ('JSONB', False)},
              'fks': [('insight_id', 'insights', 'insight_id')],
              'indexes': [],
              'pk': ['id']},
 'insights': {'columns': {'cache_version': ('TEXT', False),
                          'company_id': ('TEXT', False),
                          'created_at': ('TIMESTAMP WITH TIME ZONE', False),
                          'insight_id': ('TEXT', False),
                          'news_id': ('TEXT', False),
                          'payload': ('JSONB', False),
                          'role': ('TEXT', False)},
              'fks': [('company_id', 'companies', 'company_id'), ('news_id', 'news', 'news_id')],
              'indexes': ['insights_cache_idx'],
              'pk': ['insight_id']},
 'llm_usage': {'columns': {'calls': ('INTEGER', False),
                           'cost': ('NUMERIC', False),
                           'day': ('DATE', False),
                           'errors': ('INTEGER', False),
                           'tokens': ('BIGINT', False)},
               'fks': [],
               'indexes': [],
               'pk': ['day']},
 'news': {'columns': {'kind': ('TEXT', False),
                      'news_id': ('TEXT', False),
                      'payload': ('JSONB', False),
                      'published_at': ('TIMESTAMP WITH TIME ZONE', False)},
          'fks': [],
          'indexes': ['news_published_idx'],
          'pk': ['news_id']},
 'tool_audit': {'columns': {'created_at': ('TIMESTAMP WITH TIME ZONE', False),
                            'id': ('BIGINT', False),
                            'payload': ('JSONB', False),
                            'request_id': ('TEXT', False)},
                'fks': [],
                'indexes': ['tool_audit_request_idx'],
                'pk': ['id']}}


def _adopt_legacy():
    from alembic import context
    if context.is_offline_mode():
        return False
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("schema_migrations"):
        return False
    legacy = sa.Table("schema_migrations", sa.MetaData(), autoload_with=conn)
    rows = conn.execute(sa.select(legacy.c.version, legacy.c.checksum)).all()
    if rows != [("001_initial.sql", LEGACY_CHECKSUM)]:
        raise RuntimeError("Unknown legacy migration marker; refusing automatic adoption")
    for name, expected in EXPECTED.items():
        if not inspector.has_table(name):
            raise RuntimeError(f"Incomplete legacy schema: {name}")
        columns = {c["name"]: (str(c["type"].compile(dialect=conn.dialect)), c["nullable"])
                   for c in inspector.get_columns(name)}
        pk = inspector.get_pk_constraint(name)["constrained_columns"]
        fks = sorted((local, fk["referred_table"], remote)
                     for fk in inspector.get_foreign_keys(name)
                     for local, remote in zip(fk["constrained_columns"], fk["referred_columns"]))
        indexes = sorted(i["name"] for i in inspector.get_indexes(name))
        if columns != expected["columns"] or pk != expected["pk"] or fks != expected["fks"] or indexes != expected["indexes"]:
            raise RuntimeError(f"Legacy schema differs from the recorded version: {name}")
    checks = inspector.get_check_constraints("bank_theses")
    if not any(c["sqltext"].replace("(", "").replace(")", "").strip() == "page > 0" for c in checks):
        raise RuntimeError("Missing legacy thesis page constraint")
    # No application tables or records change. Alembic takes over versioning.
    op.drop_table("schema_migrations")
    return True


def upgrade():
    if _adopt_legacy():
        return
    op.create_table('app_state',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('bank_documents',
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('doc_id')
    )
    op.create_table('bank_products',
    sa.Column('product_id', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('product_id')
    )
    op.create_table('companies',
    sa.Column('company_id', sa.Text(), nullable=False),
    sa.Column('sector', sa.Text(), nullable=False),
    sa.Column('revenue', sa.Numeric(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('company_id')
    )
    op.create_index('companies_sector_idx', 'companies', ['sector'], unique=False)
    op.create_table('events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('llm_usage',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('tokens', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('cost', sa.Numeric(), server_default='0', nullable=False),
    sa.Column('calls', sa.Integer(), server_default='0', nullable=False),
    sa.Column('errors', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('day')
    )
    op.create_table('news',
    sa.Column('news_id', sa.Text(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('news_id')
    )
    op.create_index('news_published_idx', 'news', [sa.literal_column('published_at DESC')], unique=False)
    op.create_table('tool_audit',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('request_id', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('tool_audit_request_idx', 'tool_audit', ['request_id'], unique=False)
    op.create_table('bank_theses',
    sa.Column('thesis_id', sa.Text(), nullable=False),
    sa.Column('doc_id', sa.Text(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint('page > 0', name='bank_theses_page_check'),
    sa.ForeignKeyConstraint(['doc_id'], ['bank_documents.doc_id'], ),
    sa.PrimaryKeyConstraint('thesis_id')
    )
    op.create_table('insights',
    sa.Column('insight_id', sa.Text(), nullable=False),
    sa.Column('company_id', sa.Text(), nullable=False),
    sa.Column('news_id', sa.Text(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('cache_version', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.company_id'], ),
    sa.ForeignKeyConstraint(['news_id'], ['news.news_id'], ),
    sa.PrimaryKeyConstraint('insight_id')
    )
    op.create_index('insights_cache_idx', 'insights', ['company_id', 'role', 'news_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('answers',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('insight_id', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['insight_id'], ['insights.insight_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('feedback',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('insight_id', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['insight_id'], ['insights.insight_id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('feedback')
    op.drop_table('answers')
    op.drop_index('insights_cache_idx', table_name='insights')
    op.drop_table('insights')
    op.drop_table('bank_theses')
    op.drop_index('tool_audit_request_idx', table_name='tool_audit')
    op.drop_table('tool_audit')
    op.drop_index('news_published_idx', table_name='news')
    op.drop_table('news')
    op.drop_table('llm_usage')
    op.drop_table('events')
    op.drop_index('companies_sector_idx', table_name='companies')
    op.drop_table('companies')
    op.drop_table('bank_products')
    op.drop_table('bank_documents')
    op.drop_table('app_state')
