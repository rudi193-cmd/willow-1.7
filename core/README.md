# core/ — Storage Layers: SOIL and LOAM
<!-- b17: C0R31 · ΔΣ=42 -->

This directory contains the two storage layers that underpin the entire system.

```
core/
├── willow_store.py   # SOIL — SQLite per-collection local store
└── pg_bridge.py      # LOAM — Postgres knowledge graph bridge
```

They are intentionally separate. SOIL is always available — it requires no external process, no network, no configuration. LOAM requires Postgres and is optional at runtime; the MCP server degrades gracefully if the connection fails.

---

## SOIL — `willow_store.py`

**S**tore · **O**rganize · **I**ndex · **L**ayer

SOIL is a local, portless key/value store backed by SQLite. Every collection gets its own `store.db` file. There is no schema migration, no shared connection pool, and no network dependency.

### Structure

```
store/
  knowledge/atoms/store.db
  knowledge/edges/store.db
  agents/hanuman/store.db
  journal/entries/store.db
  …
```

Each `store.db` has two tables:
- `records` — the data (`id`, `data` JSON blob, `created_at`, `updated_at`, `deleted`, `deviation`, `action`)
- `audit_log` — every create/update/delete, with deviation and action recorded

### The Angular Deviation Rubric

Every write to SOIL carries a `deviation` parameter (float, in radians). This is the governance mechanism:

| Deviation magnitude | Action | Meaning |
|---|---|---|
| `< π/4` (~0.785) | `work_quiet` | Routine change. Proceed silently. |
| `π/4 – π/2` | `flag` | Significant change. Log prominently. |
| `> π/2` (~1.571) | `stop` | Major change. Requires human ratification. |
| `= π` | `stop` (hard ceiling) | Direction reversal. Always stops. |

The action is stored on the record and returned to the caller. Callers decide what to do with a `stop` — the store does not block the write; it just reports. (The gate layer blocks if a stream is frozen by a crisis proposal.)

### Content Triggers and Proposals

Beyond deviation thresholds, SOIL has content-triggered `FlagTrigger` rules that fire on write regardless of deviation:

- **Crisis** — patterns like "suicidal" or "want to die" → `freeze=True` Proposal
- **Minor protection** — "underage", "child abuse" → `freeze=True` Proposal
- **Positive milestone** — "goal achieved", "breakthrough" → informational Proposal
- **Positive trajectory** — deviation ≥ π/4 → milestone Proposal

When a trigger fires, it creates a `Proposal` object (kind, reason, stream, record_id). If the stream is frozen by a pending crisis Proposal, subsequent writes to that stream are blocked until the Proposal is ratified or dismissed.

### Path Security

Collection names are sanitized before use: only alphanumeric, underscore, hyphen, and slash allowed. Path traversal (`..`) is stripped. Symlinks are blocked. Records are hard-limited to 100KB.

### Key Methods

```python
store = WillowStore("/path/to/store/root")

# Write (append-only — raises if ID already exists)
rid, action, proposals = store.put("knowledge/atoms", {"title": "…"}, deviation=0.3)

# Update existing record (audit-trailed)
rid, action, proposals = store.update("knowledge/atoms", rid, {"title": "…updated…"})

# Read
record = store.get("knowledge/atoms", rid)
records = store.all("knowledge/atoms")

# Search (SQL LIKE across one collection, or all collections)
results = store.search("knowledge/atoms", "query term")
results = store.search_all("query term")   # the 'go ask Willow' pattern

# Graph edges (stored as records in knowledge/edges)
store.add_edge(from_id, to_id, "relates_to", context="…")
edges = store.edges_for(record_id)

# Stats + audit
stats = store.stats()            # counts and trajectory per collection
log = store.audit_log("knowledge/atoms", limit=20)

# Soft delete (audit-trailed; invisible to search/get but preserved)
store.delete("knowledge/atoms", rid)
```

### Trajectory

`stats()` computes a net trajectory for each collection by taking a weighted sum of all non-zero deviations:
- Positive-weighted deviations → `improving`
- Negative-weighted deviations → `degrading`
- Near-zero → `stable`

This gives a quick read on whether a collection is growing, shrinking, or stable — without reading every record.

---

## LOAM — `pg_bridge.py`

**L**ayer · **O**f · **A**ccumulated · **M**emory

LOAM is the bridge to Willow's Postgres knowledge graph. It connects via Unix socket (no host, no port, no password — just OS-level peer authentication). If Postgres is unavailable, `try_connect()` returns `None` and the MCP server continues running in SOIL-only mode.

### Connection

```python
from pg_bridge import try_connect

pg = try_connect()   # returns PgBridge or None
if pg:
    results = pg.search_knowledge("query")
```

Connection parameters come from environment variables:

| Variable | Default | Notes |
|---|---|---|
| `WILLOW_PG_DB` | `willow` | Database name |
| `WILLOW_PG_USER` | `$(whoami)` | Unix socket peer auth — no password |
| `WILLOW_PG_HOST` | unset | Only set this to force TCP (debugging) |

### Postgres Schemas

The `willow` database uses multiple schemas:

| Schema | Owner | Contents |
|---|---|---|
| `public` | system | `knowledge`, `entities`, `knowledge_edges`, `kart_task_queue`, `nest_review_queue` |
| `ganesha` | ganesha | `atoms`, `edges`, `handoffs` |
| `opus` | opus | `atoms`, `feedback`, `journal` |
| `hanuman` | hanuman | `raw_jsonls`, `atoms`, `edges`, `feedback`, `handoffs` |
| `heimdallr` | heimdallr | Same agent pipeline tables |
| (others) | per-agent | Created by `willow_agent_create` |

### Key Tables

**`knowledge`** — the global knowledge graph. Stores atoms: title, summary, category, source, search vector (PostgreSQL full-text).

**`entities`** — named entities extracted from the corpus. Tracked by mention count.

**`knowledge_edges`** — weighted directed edges between knowledge atoms.

**`kart_task_queue`** — task queue for KART. Columns: `task_id`, `agent`, `task`, `status` (pending/running/complete/failed), `result`, `created_at`, `completed_at`.

**`nest_review_queue`** — staged files awaiting human approval. Created by `nest_intake.py`.

### Key Methods

```python
# Search
pg.search_knowledge("query", limit=20)     # full-text search on public knowledge
pg.search_entities("name", limit=20)       # entity lookup
pg.search_ganesha("query")                 # search ganesha.atoms
pg.search_opus("query")                    # search opus.atoms

# Write
pg.ingest_atom(title, summary, source_type, source_id, category)
pg.ingest_ganesha_atom(content, domain, depth)
pg.ingest_opus_atom(content, domain, depth)

# Task queue
pg.submit_task(task, submitted_by, agent)  # enqueue a task
pg.claim_task(agent)                       # claim next pending task (FOR UPDATE SKIP LOCKED)
pg.complete_task(task_id, result, steps)   # mark done
pg.fail_task(task_id, error)              # mark failed
pg.pending_tasks(agent, limit)             # list queue

# Agent pipeline
pg.agent_create(name, trust, role, folder_root)   # create agent schema + folders
pg.jeles_register_jsonl(agent, path, session_id)  # register a JSONL
pg.jeles_extract_atom(agent, jsonl_id, content)   # extract atom (certainty > 0.95)
pg.binder_file(agent, jsonl_id, dest_path)        # copy to .tmp/
pg.binder_propose_edge(agent, source, target, edge_type)
pg.ratify(agent, jsonl_id, approve, cache_path)   # promote .tmp/ → cache/

# Utility
pg.gen_id(length=5)    # BASE 17 ID
pg.stats()             # row counts across all tables
pg.ping()              # connection check
```

### BASE 17 IDs

`PgBridge.gen_id()` generates short IDs using a 21-character alphabet: `0-9ACEHKLNRTXZ`. This alphabet was chosen to eliminate visually ambiguous characters (0/O, 1/I/l, 5/S, 8/B, etc.). Five characters gives ~4.1 million unique combinations — sufficient for session-scoped identifiers.

Example: `H6H23`, `5AAN0`, `K17W0`

---

## Retrieval Cascade

When an agent needs information, the system checks layers in order:

```
1. local WillowStore   → search_all() — fast, no network, always available
2. Postgres (LOAM)     → search_knowledge() — full-text, ranked by relevance
3. fleet generation    → willow_chat() → Ollama → free fleet fallback
```

The MCP server's `willow_knowledge_search` tool queries all three Postgres spaces (public knowledge, ganesha atoms, entities) in a single call.
