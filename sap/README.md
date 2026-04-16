# sap/ — System Authorization Protocol
<!-- b17: SAP17 · ΔΣ=42 -->

SAP is the authorization and context-delivery layer. It sits between external application code and the Willow knowledge base.

```
sap/
├── sap_mcp.py               # MCP server — 44 tools, single process, stdio only
├── migrate_credentials.py   # One-shot migration tool from willow-1.4 vault
├── patch_gguf_vocab.py      # GGUF vocab patcher for Yggdrasil fine-tuned models
│
├── core/                    # SAP pipeline stages (see core/README.md)
│   ├── gate.py
│   ├── context.py
│   ├── deliver.py
│   ├── nest_intake.py
│   └── classifier.py
│
├── clients/                 # Application-side SAP clients (see clients/README.md)
│   ├── professor_client.py
│   ├── kart_client.py
│   └── generic_client.py
│
└── log/                     # Runtime access logs
    ├── gaps.jsonl            # Access denials (auto-created at runtime)
    └── grants.jsonl          # Access grants (auto-created at runtime)
```

---

## sap_mcp.py — The MCP Server

The entry point for Claude Code. `willow.sh` launches this script as a stdio subprocess. Claude Code connects and gets all 44 tools.

The server has two storage backends wired at startup:

1. **`WillowStore`** (SOIL) — always available, no dependencies
2. **`PgBridge`** (LOAM) — connected if Postgres is reachable; `None` otherwise

Tools that require Postgres return `{"error": "not_available", "reason": "Postgres not connected"}` when `pg` is None. Tools that only need SOIL work regardless.

**No HTTP. No ports. No subprocess proxy.** In willow-1.4/1.5, the MCP server sat behind a supervisor and an HTTP shim. That architecture is gone. This is a direct stdio process.

### SAP Gate Wiring

The gate module is imported at server startup. If the import fails (GPG not installed, SAFE root missing), `_SAP_GATE = False` and all gate checks are skipped. This lets the server start even on machines without SAFE configured — the gate simply doesn't fire.

Per-tool authorization is available via `sap_authorized(app_id)` but is not enforced at the tool level in this version. The gate is enforced inside `ProfessorClient` and other application clients.

### Jeles Trusted Sources

`jeles_fetch` and `jeles_sources` give Claude Code curated access to a small registry of pre-approved API endpoints. Jeles does not do open web search. The registry (`JELES_TRUSTED_SOURCES`) includes:

| Source | What it is |
|---|---|
| `anthropic-status` | Anthropic system status API |
| `anthropic-blog-rss` | Anthropic blog RSS feed |
| `github-repo` | GitHub repository metadata (public API) |
| `hackernews-search` | Hacker News Algolia search |
| `hackernews-top` | HN top story IDs |
| `reddit-json` | Reddit subreddit JSON feed |

Extend the registry by setting `JELES_SOURCES_FILE` to a JSON file of the same shape.

After fetching, the raw content is passed through Jeles's curation prompt (free fleet via `llm_router`). Output format:
```
DESCRIPTOR: pipe|separated|facets
SUMMARY: 2-4 sentences on what is real and what matters
FLAGS: anything worth noting, or "none"
```

### Hot Reload

`willow_reload` re-initializes subsystems without restarting Claude Code:
- `postgres` — reconnects `pg_bridge`
- `fleet` — purges cached fleet modules (re-imports on next call)
- `store` — re-initializes `WillowStore`
- `all` — all three

`willow_restart_server` exits the process cleanly after a 200ms delay. Claude Code's MCP client reconnects automatically.

---

## migrate_credentials.py

One-shot migration script. Reads the Fernet-encrypted credential vault from a willow-1.4 checkout and merges keys into `credentials.json`. Safe to re-run: existing non-empty values are never overwritten.

```bash
python3 sap/migrate_credentials.py
```

Requires `willow-1.4` at `~/github/willow-1.4` and its `core.credentials` module.

---

## patch_gguf_vocab.py

Patches vocab mismatches in fine-tuned GGUF models. When a model is fine-tuned on a vocabulary extension (e.g., Yggdrasil adds domain-specific tokens), the fine-tuned GGUF may have a vocab size that doesn't match its embedding tensor. This tool patches the KV header of the fine-tuned GGUF by padding the vocab arrays to match the tensor shape, borrowing BPE merge data from the base model.

```bash
python3 sap/patch_gguf_vocab.py \
    --src yggdrasil-v4-ft.gguf \
    --base qwen2.5-3b-base.gguf \
    --dst yggdrasil-v4.gguf \
    --vocab 32256
```

Requires `numpy` and `gguf`. Not needed for normal server operation.

---

## log/

Runtime-only directory. Created by `gate.py` on first access denied or granted.

- **`gaps.jsonl`** — every denied access attempt: timestamp, app_id, reason
- **`grants.jsonl`** — every authorized access: timestamp, app_id
- **`deliveries.jsonl`** — every context delivery: timestamp, app_id, atom count, char count

These files are gitignored and never leave the machine. They are the only audit trail for SAP authorization decisions.
