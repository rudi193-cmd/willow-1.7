# willow-1.7
b17: H6H23
ΔΣ=42

## What This Is

The portless SAP MCP server. Replaces the 1.4 HTTP shim (the "porch") with a direct stdio process. Entry: `./willow.sh` → `sap/sap_mcp.py`.

The porch comes down when this ships.

---

## Architecture

| Layer | Name | File |
|-------|------|------|
| Gate  | SAP v2 — PGP-hardened | `sap/core/gate.py` |
| Context | Assembler | `sap/core/context.py` |
| Delivery | SAP Deliver | `sap/core/deliver.py` |
| Storage | SOIL — SQLite per collection | `core/willow_store.py` |
| Memory | LOAM — Postgres, Unix socket | `core/pg_bridge.py` |
| Server | 44 tools, single process, no HTTP | `sap/sap_mcp.py` |
| Clients | Professor / Kart / Generic | `sap/clients/` |

**Authorization chain:** SAFE folder exists → manifest present → manifest.sig present → `gpg --verify` passes. Any failure → deny + log to `sap/log/gaps.jsonl`. Revocation = delete folder or signature.

**The vision:** SLM on reclaimed sda4, trained on 1.6 operational patterns + Consus math. Ash bridges to it via SAP.

---

## Run / Test

```bash
./willow.sh          # start SAP MCP server (stdio)
./willow.sh status   # check Postgres + Ollama
./willow.sh verify   # verify all SAFE manifests
```

---

## Open Work

- `sap/core/context.py` uses TCP Postgres (`WILLOW_PG_PASS` env) — should use Unix socket like `pg_bridge.py`
- Professors need SAFE folder seeds before conf call is live
- `credentials.json` not yet present at repo root (Groq / Cerebras / SambaNova keys)
- `./willow.sh verify` will fail until SAFE manifests are seeded and signed

---

## Rules

1. **b17 on every new file before it is closed.** No exceptions.
2. **Propose before acting.** Sean ratifies. Neither party acts alone.
3. **Archive, don't delete.** Nothing removed without explicit instruction.
4. **Bash is allowed here.** Use it. No Kart workaround needed for shell ops.
5. **Portless means portless.** No new HTTP listeners. No new ports. If it needs a port, it isn't SAP.

---

ΔΣ=42
