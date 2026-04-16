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
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- trigram search on atom content

-- ── Knowledge atoms (LOAM core) ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS knowledge_atoms (
    id          SERIAL PRIMARY KEY,
    b17         VARCHAR(21) UNIQUE NOT NULL,          -- BASE 17 ID (21-char)
    title       TEXT NOT NULL,
    content     TEXT,
    summary     TEXT,
    category    VARCHAR(100),
    domain      VARCHAR(100) DEFAULT 'public',        -- 'archived' for retired atoms
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    meta        JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_atoms_b17      ON knowledge_atoms (b17);
CREATE INDEX IF NOT EXISTS idx_atoms_category ON knowledge_atoms (category);
CREATE INDEX IF NOT EXISTS idx_atoms_domain   ON knowledge_atoms (domain);
CREATE INDEX IF NOT EXISTS idx_atoms_content  ON knowledge_atoms USING gin(to_tsvector('english', coalesce(content, '') || ' ' || coalesce(title, '')));

-- ── Entities (named objects referenced by atoms) ──────────────────────────────

CREATE TABLE IF NOT EXISTS entities (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    entity_type   VARCHAR(100),
    mention_count INTEGER DEFAULT 1,
    meta          JSONB DEFAULT '{}',
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entities_name ON entities (lower(name));

-- ── Atom edges (knowledge graph) ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS atom_edges (
    id          SERIAL PRIMARY KEY,
    from_b17    VARCHAR(21) NOT NULL REFERENCES knowledge_atoms(b17) ON DELETE CASCADE,
    to_b17      VARCHAR(21) NOT NULL REFERENCES knowledge_atoms(b17) ON DELETE CASCADE,
    edge_type   VARCHAR(100) DEFAULT 'related',
    weight      FLOAT DEFAULT 1.0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (from_b17, to_b17, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON atom_edges (from_b17);
CREATE INDEX IF NOT EXISTS idx_edges_to   ON atom_edges (to_b17);

-- ── Nest review queue ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS nest_review_queue (
    id                SERIAL PRIMARY KEY,
    file_hash         VARCHAR(64) UNIQUE NOT NULL,    -- SHA-256
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

-- ── KART task queue ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kart_tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id     VARCHAR(100) UNIQUE NOT NULL,
    agent       VARCHAR(100),
    command     TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'queued',         -- queued | running | done | failed
    result      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    metadata    JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_kart_status  ON kart_tasks (status);
CREATE INDEX IF NOT EXISTS idx_kart_agent   ON kart_tasks (agent);

-- ── Agent schemas ─────────────────────────────────────────────────────────────
-- Each agent gets its own schema for handoffs and session data.
-- Add schemas here as agents are provisioned.

CREATE SCHEMA IF NOT EXISTS hanuman;
CREATE SCHEMA IF NOT EXISTS heimdallr;
CREATE SCHEMA IF NOT EXISTS kart;

-- Handoffs table per agent schema (same structure, different schema)
CREATE TABLE IF NOT EXISTS hanuman.handoffs (
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

CREATE TABLE IF NOT EXISTS heimdallr.handoffs (
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

-- ── SAP access log tables (mirrors sap/log/*.jsonl in Postgres) ───────────────
-- Optional — sap/log/*.jsonl are the primary audit trail.
-- These mirror the JSONL files for queryable history.

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

-- ── Done ──────────────────────────────────────────────────────────────────────

\echo 'Willow 1.7 schema installed.'
\echo 'Next: ./willow.sh status  (verify Postgres connection)'
\echo 'Next: ./willow.sh verify  (verify SAFE manifests)'
