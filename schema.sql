-- schema.sql — Willow 1.7 base Postgres schema
-- b17: (assign on commit)
-- ΔΣ=42
--
-- Run once on a fresh machine to create the LOAM database structure.
-- All tables are created in the `public` schema unless otherwise noted.
--
-- Usage:
--   psql -d willow -f schema.sql
--
-- Or via willow.sh (planned):
--   ./willow.sh init
--
-- Requires: Postgres 14+, peer auth for local Unix socket connections.
-- The `willow` database must already exist:
--   createdb willow

-- ── Extensions ────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- trigram search
CREATE EXTENSION IF NOT EXISTS "unaccent";   -- accent-insensitive FTS

-- ── Knowledge atoms (LOAM core) ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS knowledge (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    summary         TEXT,
    source_type     TEXT,
    source_id       TEXT,
    category        VARCHAR(100) DEFAULT 'general',
    lattice_domain  VARCHAR(100),
    lattice_type    VARCHAR(100),
    lattice_status  VARCHAR(100),
    created_at      TEXT DEFAULT (NOW()::text),
    search_vector   TSVECTOR
);

CREATE INDEX IF NOT EXISTS idx_knowledge_category      ON knowledge (category);
CREATE INDEX IF NOT EXISTS idx_knowledge_domain        ON knowledge (lattice_domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_search        ON knowledge USING gin(search_vector);

-- Auto-update search_vector on insert/update
CREATE OR REPLACE FUNCTION knowledge_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.summary, '')), 'B');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS knowledge_search_vector_trigger ON knowledge;
CREATE TRIGGER knowledge_search_vector_trigger
    BEFORE INSERT OR UPDATE ON knowledge
    FOR EACH ROW EXECUTE FUNCTION knowledge_search_vector_update();

-- ── Entities (named objects referenced by atoms) ──────────────────────────────

CREATE TABLE IF NOT EXISTS entities (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    entity_type     VARCHAR(100),
    domain          VARCHAR(100),
    first_seen      TIMESTAMPTZ DEFAULT NOW(),
    mention_count   INTEGER DEFAULT 1,
    meta            JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_entities_name   ON entities (lower(name));
CREATE INDEX IF NOT EXISTS idx_entities_domain ON entities (domain);

-- ── Knowledge edges (knowledge graph) ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS knowledge_edges (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES knowledge(id) ON DELETE CASCADE,
    target_id   INTEGER NOT NULL REFERENCES knowledge(id) ON DELETE CASCADE,
    edge_type   VARCHAR(100) DEFAULT 'related',
    weight      FLOAT DEFAULT 1.0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_id, target_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_kedges_source ON knowledge_edges (source_id);
CREATE INDEX IF NOT EXISTS idx_kedges_target ON knowledge_edges (target_id);

-- ── Kart task queue ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kart_task_queue (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id         TEXT UNIQUE NOT NULL,
    submitted_by    TEXT,
    agent           TEXT DEFAULT 'kart',
    task            TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',   -- pending | running | complete | failed
    result          TEXT,                     -- JSON
    steps           INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_kart_status ON kart_task_queue (status);
CREATE INDEX IF NOT EXISTS idx_kart_agent  ON kart_task_queue (agent);

-- ── Nest review queue ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS nest_review_queue (
    id                SERIAL PRIMARY KEY,
    file_hash         VARCHAR(64) UNIQUE NOT NULL,
    filename          TEXT NOT NULL,
    source_path       TEXT NOT NULL,
    proposed_dest     TEXT,
    category          VARCHAR(100),
    subcategory       VARCHAR(100),
    summary           TEXT,
    status            VARCHAR(20) DEFAULT 'pending',  -- pending | confirmed | skipped
    matched_entities  JSONB DEFAULT '[]',
    tos_verdict       TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_nest_status ON nest_review_queue (status);

-- ── Journal events (bridge-gate hook logging) ─────────────────────────────────

CREATE TABLE IF NOT EXISTS journal_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type  TEXT,
    username    TEXT,
    payload     JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_journal_username ON journal_events (username);

-- ── SAP access logs ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sap_grants (
    id      SERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL,
    app_id  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sap_gaps (
    id      SERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL,
    app_id  TEXT NOT NULL,
    reason  TEXT
);

-- ── Agent schemas ─────────────────────────────────────────────────────────────
-- Each agent gets its own schema.
-- Per-agent tables: raw_jsonls, atoms, edges, feedback, handoffs
-- Matches the structure created by pg_bridge.PgBridge.agent_create()

CREATE SCHEMA IF NOT EXISTS ganesha;
CREATE SCHEMA IF NOT EXISTS opus;
CREATE SCHEMA IF NOT EXISTS hanuman;
CREATE SCHEMA IF NOT EXISTS heimdallr;
CREATE SCHEMA IF NOT EXISTS kart;

-- ── Ganesha schema ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ganesha.atoms (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    title           TEXT,
    domain          TEXT DEFAULT 'meta',
    depth           INTEGER DEFAULT 1,
    source_session  TEXT,
    source_file     TEXT,
    created         TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ganesha.handoffs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    content      TEXT,
    pointer_path TEXT,
    session_date DATE DEFAULT CURRENT_DATE,
    turn_count   INTEGER,
    tools_used   JSONB DEFAULT '[]',
    b17          VARCHAR(21),
    created      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ganesha.feedback (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain      TEXT NOT NULL,
    principle   TEXT NOT NULL,
    source      TEXT DEFAULT 'self',
    created     TIMESTAMPTZ DEFAULT now()
);

-- ── Opus schema ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS opus.atoms (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    content         TEXT NOT NULL,
    title           TEXT,
    domain          TEXT DEFAULT 'meta',
    depth           INTEGER DEFAULT 1,
    source_session  TEXT,
    source_file     TEXT,
    created         TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opus.feedback (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain      TEXT NOT NULL,
    principle   TEXT NOT NULL,
    source      TEXT DEFAULT 'self',
    created     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opus.journal (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry       TEXT NOT NULL,
    session_id  TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ── Per-agent pipeline tables (hanuman / heimdallr / kart) ────────────────────
-- Matches pg_bridge.PgBridge.agent_create() exactly.

DO $$
DECLARE
    s TEXT;
BEGIN
    FOREACH s IN ARRAY ARRAY['hanuman', 'heimdallr', 'kart']
    LOOP
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.raw_jsonls (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                source_path TEXT NOT NULL,
                content_id  TEXT,
                filed_path  TEXT,
                turn_count  INTEGER,
                cwd         TEXT,
                file_size   BIGINT,
                status      TEXT DEFAULT ''pending'',
                filed_at    TIMESTAMPTZ,
                created     TIMESTAMPTZ DEFAULT now()
            )', s);
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.atoms (
                id              TEXT PRIMARY KEY,
                jsonl_id        TEXT,
                content         TEXT NOT NULL,
                title           TEXT,
                domain          TEXT DEFAULT ''meta'',
                depth           INTEGER DEFAULT 1,
                certainty       REAL DEFAULT 1.0,
                status          TEXT DEFAULT ''tmp'',
                source_session  TEXT,
                source_file     TEXT,
                created         TIMESTAMPTZ DEFAULT now()
            )', s);
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.edges (
                id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                source_id     TEXT NOT NULL,
                source_schema TEXT NOT NULL DEFAULT %L,
                target_id     TEXT NOT NULL,
                target_schema TEXT NOT NULL DEFAULT %L,
                edge_type     TEXT NOT NULL,
                weight        REAL DEFAULT 1.0,
                status        TEXT DEFAULT ''tmp'',
                created       TIMESTAMPTZ DEFAULT now(),
                UNIQUE(source_id, source_schema, target_id, target_schema, edge_type)
            )', s, s, s);
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.feedback (
                id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                domain      TEXT NOT NULL,
                principle   TEXT NOT NULL,
                source      TEXT DEFAULT ''self'',
                created     TIMESTAMPTZ DEFAULT now()
            )', s);
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I.handoffs (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id   UUID NOT NULL DEFAULT gen_random_uuid(),
                title        TEXT NOT NULL,
                content      TEXT NOT NULL,
                session_date DATE,
                working_dir  TEXT,
                turn_count   INTEGER,
                tools_used   TEXT[],
                b17          TEXT,
                pointer_path TEXT,
                created      TIMESTAMPTZ DEFAULT now()
            )', s);
    END LOOP;
END
$$;

-- ── Done ──────────────────────────────────────────────────────────────────────

\echo 'Willow 1.7 schema installed.'
\echo 'Tables: knowledge, entities, knowledge_edges, kart_task_queue, nest_review_queue, journal_events'
\echo 'Schemas: ganesha, opus, hanuman, heimdallr, kart'
\echo 'Next: ./willow.sh status'
