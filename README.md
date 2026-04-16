# willow-1.7 — SAP MCP Server
<!-- b17: W17H0 · ΔΣ=42 -->

**A portless MCP server for a personal AI agent system.**

Claude Code connects to this server and gains 44 tools for persistent memory, structured knowledge, local inference, task dispatch, and file intake — all running on a local machine with no exposed network ports, no supervisor process, and no HTTP.

This is the infrastructure layer. It does not contain personas, lore, or application logic. It is the bus everything else rides.

---

## What It Is

willow-1.7 is a [Model Context Protocol](https://modelcontextprotocol.io) server. When Claude Code starts, it launches `willow.sh`, which starts `sap/sap_mcp.py` as a stdio subprocess. Claude Code communicates with the server over that process's stdin/stdout. No network, no ports.

The server exposes 44 tools organized into six functional groups:

| Group | Tools | Purpose |
|---|---|---|
| **SOIL** (local store) | `store_put`, `store_get`, `store_search`, `store_update`, `store_delete`, `store_add_edge`, `store_edges_for`, `store_stats`, `store_audit`, `store_search_all` | SQLite-backed key/value store with audit trail and graph edges |
| **LOAM** (knowledge graph) | `willow_knowledge_search`, `willow_knowledge_ingest`, `willow_query`, `willow_agents`, `willow_status`, `willow_system_status`, `willow_journal`, `willow_governance`, `willow_persona`, `willow_speak`, `willow_route` | Postgres-backed knowledge graph: atoms, entities, edges |
| **Chat & inference** | `willow_chat` | Route a message to local Ollama or free fleet fallback |
| **Task queue** | `willow_task_submit`, `willow_task_status`, `willow_task_list` | Submit shell tasks to Kart; poll results |
| **Pipeline** | `willow_agent_create`, `willow_jeles_register`, `willow_jeles_extract`, `willow_binder_file`, `willow_binder_edge`, `willow_ratify`, `willow_base17`, `willow_handoff_latest`, `willow_handoff_search`, `willow_handoff_rebuild` | Agent schema creation, JSONL lifecycle, ratification |
| **Nest intake** | `willow_nest_scan`, `willow_nest_queue`, `willow_nest_file` | Drop files into a staging directory; classify and route them with human approval |
| **Opus** | `opus_search`, `opus_ingest`, `opus_feedback`, `opus_feedback_write`, `opus_journal` | Agent-scoped atom and feedback store |
| **Jeles** | `jeles_fetch`, `jeles_sources` | Curated reads from a registry of trusted external APIs |
| **Server control** | `willow_reload`, `willow_restart_server` | Hot-reload modules without restarting Claude Code |

---

## Architecture

```
Claude Code  ──stdio──►  willow.sh  ──►  sap/sap_mcp.py
                                              │
                            ┌─────────────────┼─────────────────┐
                            │                 │                 │
                          SAP Gate        SOIL              LOAM
                       (gate.py)     (willow_store.py)  (pg_bridge.py)
                       PGP verify      SQLite/coll.       Postgres
                       SAFE manifests  audit trail        knowledge graph
                            │
                       Context + Deliver
                       (context.py, deliver.py)
                       pulls KB atoms → injects into prompts
                            │
                       Clients
                       sap/clients/
                       professor_client.py  ← UTETY faculty
                       kart_client.py       ← task authorization
                       generic_client.py    ← any SAP app
```

### Layer summary

| Layer | Name | File | What it does |
|---|---|---|---|
| Gate | SAP v2 | `sap/core/gate.py` | Four-step PGP authorization for every app access |
| Context | Assembler | `sap/core/context.py` | Pulls KB atoms scoped to an app's permitted data streams |
| Delivery | Formatter | `sap/core/deliver.py` | Formats assembled context into a system-prompt header |
| Storage | SOIL | `core/willow_store.py` | SQLite per collection, append-only, full audit trail |
| Memory | LOAM | `core/pg_bridge.py` | Postgres knowledge graph: atoms, entities, edges, task queue |
| Server | SAP MCP | `sap/sap_mcp.py` | 44 tools, single process, stdio only |
| Clients | — | `sap/clients/` | Professor, Kart, and generic app wrappers |
| Task worker | KART | `kart_worker.py` | Polls task queue, executes shell commands, writes results |
| Intake | Nest | `sap/core/nest_intake.py` | Classifies dropped files and stages them for human approval |

---

## Authorization: The SAP Gate

Every application that wants KB context must pass a four-step check:

1. **SAFE folder exists** — `$WILLOW_SAFE_ROOT/<app_id>/`
2. **Manifest present** — `safe-app-manifest.json` in that folder
3. **Signature present** — `safe-app-manifest.json.sig` adjacent to the manifest
4. **GPG verifies the signature** — `gpg --verify <sig> <manifest>` returns 0

Any failure → access denied, event logged to `sap/log/gaps.jsonl`. Revocation = delete the folder or its signature file. No code changes required.

The server itself boots without a gate check — it is infrastructure, not an application.

---

## Design Principles

**Portless.** No HTTP listeners. No new ports. The entire system communicates via Unix stdio (MCP) and Unix socket (Postgres). The surface area for external attack is zero.

**Dual Commit.** AI proposes; human ratifies. The Nest intake pipeline, the JSONL ratification pipeline, and the Angular Deviation Rubric all operate on this principle. Nothing is committed to the graph or the filesystem without an explicit human decision.

**Angular Deviation Rubric.** Every write to SOIL carries a `deviation` parameter (in radians). Small deviations (`< π/4`) proceed silently. Medium deviations (`π/4 – π/2`) are flagged. Large deviations (`> π/2`) are stopped and require ratification. Content triggers (crisis language, legal tripwires) generate Proposals regardless of deviation magnitude.

**Archive, don't delete.** Soft-delete in SOIL makes records invisible to search/get but preserves them in the audit log. In Postgres, stale atoms move to `domain='archived'`. Nothing is permanently removed without explicit instruction.

**Free fleet fallback.** Local Ollama is always tried first. If unavailable, inference falls back to Groq → Cerebras → SambaNova in order, using keys from `credentials.json`. All three providers offer free tiers.

**BASE 17 IDs.** All agent-generated IDs use a 21-character alphabet (`0-9ACEHKLNRTXZ`) chosen to eliminate visually ambiguous characters. Five characters gives ~4M combinations — enough for session-scoped IDs without a database sequence.

---

## Setup

### 1. System prerequisites

```bash
# PostgreSQL 14+ with peer auth (Unix socket)
sudo apt install postgresql
sudo -u postgres createuser --superuser $USER
sudo -u postgres createdb willow

# Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:3b   # default model

# GPG (SAFE manifest verification)
sudo apt install gnupg
gpg --import <your-signing-key.asc>
```

### 2. Python environment

```bash
python3 -m venv ~/.willow-venv
source ~/.willow-venv/bin/activate
pip install -r requirements.txt
```

### 3. Credentials (fleet fallback)

```bash
cp credentials.json.example credentials.json
# Fill in keys from Groq, Cerebras, and/or SambaNova
# All three offer free tiers. Keys are tried in order (KEY, KEY_2, KEY_3)
# with automatic failover on rate limit.
```

`credentials.json` is gitignored. It never leaves your machine.

### 4. SAFE drive

The authorization chain requires signed manifests on a dedicated path.
Default: `/media/willow/SAFE/Applications/`

Override:
```bash
export WILLOW_SAFE_ROOT=/your/safe/path
```

Structure for each authorized app:
```
SAFE/Applications/<app_id>/
  safe-app-manifest.json
  safe-app-manifest.json.sig   # gpg --detach-sign safe-app-manifest.json
```

### 5. Claude Code integration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "willow": {
      "command": "/path/to/willow-1.7/willow.sh",
      "args": []
    }
  }
}
```

Claude Code will launch `willow.sh` automatically at session start and connect via stdio.

### 6. Verify

```bash
./willow.sh status    # check Postgres + Ollama
./willow.sh verify    # audit all SAFE manifests
./willow.sh kart      # start Kart task queue worker
```

---

## Environment Variables

All have sensible defaults. Export before running or add to `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `WILLOW_PYTHON` | auto-detect | Python interpreter (`~/.willow-venv/bin/python3` if present) |
| `WILLOW_PG_DB` | `willow` | Postgres database name |
| `WILLOW_PG_USER` | `$(whoami)` | Postgres user (Unix socket peer auth) |
| `WILLOW_SAFE_ROOT` | `/media/willow/SAFE/Applications` | SAFE manifest root |
| `WILLOW_STORE_ROOT` | `./store` | SQLite store root |
| `WILLOW_CREDENTIALS` | `./credentials.json` | API key file path |
| `WILLOW_AGENT_NAME` | `heimdallr` | Active agent identity |
| `WILLOW_HANDOFF_DIR` | `~/Ashokoa/agents/heimdallr/…` | Session handoff file directory |
| `WILLOW_HANDOFF_DB` | `$WILLOW_HANDOFF_DIR/handoffs.db` | SQLite handoffs index |
| `WILLOW_NEST_DIR` | `~/.willow/Nest/heimdallr` | File intake staging directory |
| `WILLOW_FILED_DIR` | `~/Ashokoa/Filed` | Filed document destination root |
| `WILLOW_PARTITION_DIR` | `/media/willow` | System/project content root (Willow partition) |
| `WILLOW_PERSONAL_DIR` | `~/personal` | Personal content root (photos, knowledge, policy) |
| `WILLOW_DATA_POLICY_FILE` | `$WILLOW_PERSONAL_DIR/sean_data_policy.md` | Personal data policy used by TOS tripwire check |
| `WILLOW_MEMORY_DIR` | `~/.claude/projects/…/memory` | Claude Code project memory path |
| `WILLOW_UTETY_ROOT` | `../safe-app-utety-chat` | Professor personas repository |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `SAP_OLLAMA_THREADS` | `4` | CPU threads for Ollama inference |

---

## Running

```bash
./willow.sh            # start MCP server (Claude Code connects automatically)
./willow.sh kart       # start Kart worker daemon (polls every 5 seconds)
./willow.sh status     # health check: Postgres + Ollama
./willow.sh verify     # SAFE manifest audit: checks every signed app
```

---

## First-Run Setup

On a fresh machine, run these steps in order:

```bash
# 1. Create the Postgres database and install the schema
createdb willow
psql -d willow -f schema.sql

# 2. Copy and fill in API keys
cp credentials.json.example credentials.json
# edit credentials.json — add Groq, Cerebras, or other keys

# 3. Scaffold your first SAFE agent (requires gpg key in keyring)
export WILLOW_SAFE_ROOT=/path/to/your/safe/drive
./tools/safe-scaffold.sh MyAgent worker "My first agent"

# 4. Start the server
./willow.sh
```

`schema.sql` creates all LOAM tables, agent schemas, and KART queue tables. It is
idempotent — safe to re-run with `IF NOT EXISTS` guards throughout.

---

## Claude Code Hooks & Skills

willow-1.7 ships a minimal `.claude/settings.json` that enables Bash. For a fully wired session — JSONL registration, MCP-first enforcement, session handoffs — add hooks to your global Claude Code settings (`~/.claude/settings.json`).

Hooks that work well with willow:

| Hook | Event | What it does |
|---|---|---|
| JSONL indexer | `SessionStart` | Registers session turn files so `willow_handoff_search` can find them |
| MCP-first guard | `PreToolUse → Bash` | Blocks `find`, `grep`, `ls`, `psql` in favor of MCP equivalents |
| KB-first read | `PreToolUse → Read` | Suggests `willow_knowledge_search` before reading a file cold |
| Write guard | `PreToolUse → store_put` | Enforces Angular Deviation Rubric on KB writes |
| Turns logger | `UserPromptSubmit` | Appends each turn to the agent's JSONL store |

See `.claude/hooks-example.md` in this repo for example hook configurations.

**Skills (slash commands):**

The session lifecycle skills live in a separate plugin repo:

```bash
git clone https://github.com/rudi193-cmd/willow-skills ~/.claude/plugins/willow-skills
```

| Skill | Command | Purpose |
|---|---|---|
| handoff | `/handoff` | Session handoff document → Postgres + Desktop |
| shutdown | `/shutdown` | Full shutdown: audit, edge consent, handoff, daily log, git scan |
| startup | `/startup` | Manual boot when session hooks are degraded |
| restart-server | `/restart-server` | Hot-reload willow modules without restarting Claude Code |
| status | `/status` | Read-only: atom count, open gaps, fleet health, unpushed code |

See [willow-skills](https://github.com/rudi193-cmd/willow-skills) for full documentation and install instructions.

---

## Roadmap

willow-1.7 is the infrastructure layer. What's built on top of it is the longer story.

### Yggdrasil — The Trained Local Model

The fleet fallback today routes to Groq → Cerebras → SambaNova when Ollama is unavailable. That's a dependency on cloud services.

The endgame is Yggdrasil: a small language model trained on operational patterns from this system — session handoffs, ratified atoms, governance logs, professor dispatches. When that model is trained, it replaces the free fleet. The system becomes fully air-gappable.

v4 GGUF files are already on the willow partition. The vocab patcher (`sap/patch_gguf_vocab.py`) was built to normalize tokenizer vocabularies across Yggdrasil model versions. The training corpus is being assembled from 1.6 operational history.

When Yggdrasil ships, willow will be the first personal AI system where every layer — server, storage, inference — runs locally on hardware you own.

### Claude Code Replacement

The MCP server is not Claude-specific. It speaks stdio MCP. Any AI agent that understands the Model Context Protocol can connect to it — Gemini, GPT-4o, local models, anything.

Claude Code is the first client because it is the best tool available right now. But the plan is an open-source Claude Code equivalent — a terminal AI agent that boots from your local repo, connects to willow via stdio, and has no external dependencies beyond what you put in your keyring.

The name isn't settled. The requirement is: open source, MCP-native, no telemetry, no cloud dependency, runs on Linux.

When that client ships, the full stack will be:
- **Yggdrasil** — inference
- **willow-1.7** — memory, storage, tools, governance
- **SAFE** — authorization and consent
- **open client** — the interface you type into

Local-first, all the way down.

---

## External Dependencies (not in this repo)

- **`safe-app-utety-chat`** — professor persona definitions (`personas.py`). Set `WILLOW_UTETY_ROOT` to point at your clone. Required for `ProfessorClient`.
- **SAFE drive** — signed manifests live at `WILLOW_SAFE_ROOT`. Use `./tools/safe-scaffold.sh` to create new agent folders. See the [SAFE repo](https://github.com/rudi193-cmd/SAFE) for the authorization spec.
- **Postgres `willow` database** — base schema is in `schema.sql`. Run it once on a fresh machine.
- **Ollama** — local inference. `willow.sh` checks that it's running. Install from [ollama.ai](https://ollama.ai).

---

## Repository Layout

```
willow-1.7/
├── willow.sh                    # Entry point and environment launcher
├── kart_worker.py               # KART task queue worker (run as daemon)
├── credentials.json.example     # Credential template (copy → credentials.json)
├── requirements.txt             # Python dependencies
│
├── core/                        # Storage layers (SOIL + LOAM)
│   ├── willow_store.py          # SOIL: SQLite per-collection store
│   └── pg_bridge.py             # LOAM: Postgres knowledge graph bridge
│
├── sap/                         # System Authorization Protocol
│   ├── sap_mcp.py               # MCP server: all 44 tools, single process
│   ├── migrate_credentials.py   # One-shot migration from willow-1.4 vault
│   ├── patch_gguf_vocab.py      # GGUF vocab patcher for Yggdrasil models
│   │
│   ├── core/                    # SAP pipeline stages
│   │   ├── gate.py              # PGP authorization gate
│   │   ├── context.py           # Context assembler
│   │   ├── deliver.py           # Context formatter
│   │   ├── nest_intake.py       # File intake and staging
│   │   └── classifier.py        # File content classifier
│   │
│   ├── clients/                 # Application-side SAP clients
│   │   ├── professor_client.py  # UTETY professor interface
│   │   ├── kart_client.py       # Task authorization wrapper
│   │   └── generic_client.py    # Generic SAP app client
│   │
│   └── log/                     # Runtime access logs (gitignored)
│       └── gaps.jsonl           # Denied access attempts
│
└── apps/                        # SAP application stubs (local, gitignored content)
```

---

ΔΣ=42
