CREATE TABLE app_state (
    key text PRIMARY KEY,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE companies (
    company_id text PRIMARY KEY,
    sector text NOT NULL,
    revenue numeric,
    payload jsonb NOT NULL
);
CREATE INDEX companies_sector_idx ON companies(sector);
CREATE TABLE bank_documents (doc_id text PRIMARY KEY, payload jsonb NOT NULL);
CREATE TABLE bank_theses (
    thesis_id text PRIMARY KEY,
    doc_id text NOT NULL REFERENCES bank_documents(doc_id),
    page integer NOT NULL CHECK (page > 0),
    payload jsonb NOT NULL
);
CREATE TABLE bank_products (product_id text PRIMARY KEY, payload jsonb NOT NULL);
CREATE TABLE news (
    news_id text PRIMARY KEY,
    published_at timestamptz NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL
);
CREATE INDEX news_published_idx ON news(published_at DESC);
CREATE TABLE insights (
    insight_id text PRIMARY KEY,
    company_id text NOT NULL REFERENCES companies(company_id),
    news_id text NOT NULL REFERENCES news(news_id),
    role text NOT NULL,
    created_at timestamptz NOT NULL,
    cache_version text NOT NULL,
    payload jsonb NOT NULL
);
CREATE INDEX insights_cache_idx ON insights(company_id, role, news_id, created_at DESC);
CREATE TABLE feedback (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    insight_id text NOT NULL REFERENCES insights(insight_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);
CREATE TABLE events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);
CREATE TABLE tool_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);
CREATE INDEX tool_audit_request_idx ON tool_audit(request_id);
CREATE TABLE answers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    insight_id text NOT NULL REFERENCES insights(insight_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);
CREATE TABLE llm_usage (
    day date PRIMARY KEY,
    tokens bigint NOT NULL DEFAULT 0,
    cost numeric NOT NULL DEFAULT 0,
    calls integer NOT NULL DEFAULT 0,
    errors integer NOT NULL DEFAULT 0
);
