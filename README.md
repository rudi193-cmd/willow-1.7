# willow-1.7 — SAP MCP Server
b17: W17H0 · ΔΣ=42

Portless MCP server for the Willow AI agent system. Replaces the HTTP shim
from 1.4/1.5 with a direct stdio process — no exposed ports, no supervisor.

Entry point: `./willow.sh` → `sap/sap_mcp.py`  
Claude Code connects via `.mcp.json`.

---

## Architecture

| Layer | Name | File |
|---|---|---|
| Gate | SAP v2 — PGP-hardened | `sap/core/gate.py` |
| Context | Assembler | `sap/core/context.py` |
| Delivery | SAP Deliver | `sap/core/deliver.py` |
| Storage | SOIL — SQLite per collection | `core/willow_store.py` |
| Memory | LOAM — Postgres, Unix socket | `core/pg_bridge.py` |
| Server | 44 tools, single process, no HTTP | `sap/sap_mcp.py` |
| Clients | Professor / Kart / Generic | `sap/clients/` |

**Authorization chain:** SAFE folder exists → manifest present → manifest.sig
present → `gpg --verify` passes. Any failure → deny + log to `sap/log/gaps.jsonl`.

---

## Setup (new machine)

### 1. System prerequisites

```bash
# PostgreSQL 14+ with peer auth (Unix socket)
sudo apt install postgresql
sudo -u postgres createuser --superuser $USER
sudo -u postgres createdb willow

# Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:3b   # default model

# GPG (for SAFE manifest verification)
sudo apt install gnupg
# Import the signing key: gpg --import <key.asc>
```

### 2. Python environment

```bash
python3 -m venv ~/.willow-venv
source ~/.willow-venv/bin/activate
pip install -r requirements.txt
```

Or with a system Python:
```bash
pip install -r requirements.txt
export WILLOW_PYTHON=$(which python3)
```

### 3. Credentials (fleet fallback)

```bash
cp credentials.json.example credentials.json
# Edit credentials.json — add Groq / Cerebras / SambaNova keys
# Keys are tried in order with automatic failover
```

### 4. SAFE drive

The authorization chain requires a SAFE folder structure. Default mount point:
`/media/willow/SAFE/Applications/`

Override with:
```bash
export WILLOW_SAFE_ROOT=/your/safe/path
```

Each app needs:
```
SAFE/Applications/<app_id>/
  safe-app-manifest.json
  safe-app-manifest.json.sig   # gpg --detach-sign
```

### 5. Environment variables

All have sensible defaults. Override as needed:

| Variable | Default | Purpose |
|---|---|---|
| `WILLOW_PYTHON` | auto-detect | Python interpreter |
| `WILLOW_PG_DB` | `willow` | Postgres database name |
| `WILLOW_PG_USER` | `$(whoami)` | Postgres user (Unix socket peer auth) |
| `WILLOW_SAFE_ROOT` | `/media/willow/SAFE/Applications` | SAFE folder root |
| `WILLOW_STORE_ROOT` | `./store` | SQLite store root |
| `WILLOW_CREDENTIALS` | `./credentials.json` | API key file |
| `WILLOW_AGENT_NAME` | `heimdallr` | Active agent identity |
| `WILLOW_HANDOFF_DIR` | `~/Ashokoa/agents/heimdallr/...` | Handoff file directory |
| `WILLOW_NEST_DIR` | `~/.willow/Nest/heimdallr` | File intake staging dir |
| `WILLOW_FILED_DIR` | `~/Ashokoa/Filed` | Filed document root |
| `WILLOW_UTETY_ROOT` | `../safe-app-utety-chat` | Professor personas repo |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |

### 6. Claude Code integration

Add to `.mcp.json` in your project:

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

### 7. Verify

```bash
./willow.sh status    # check Postgres + Ollama
./willow.sh verify    # verify all SAFE manifests (apps + professors)
./willow.sh kart      # start Kart task queue daemon
```

---

## External dependencies (not in this repo)

- **`safe-app-utety-chat`** — professor personas (`personas.py`). Set
  `WILLOW_UTETY_ROOT` to point at your clone. Required for `ProfessorClient`.
- **SAFE drive** — signed manifests live on a physical drive or configurable
  path. Not shipped with the repo.
- **Postgres `willow` database** — schema created by agent tooling. Run
  `willow_agent_create` via MCP to scaffold a new agent schema.

---

## Running

```bash
./willow.sh          # start MCP server (Claude Code connects automatically)
./willow.sh kart     # start Kart worker daemon (polls every 5s)
./willow.sh status   # health check
./willow.sh verify   # SAFE manifest audit
```

---

ΔΣ=42
