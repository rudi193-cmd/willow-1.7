# Agent Onboarding
<!-- b17: AGOB2 · ΔΣ=42 -->

How new agents join the Willow system.

## The pipeline

New agents register via the `willow-dashboard` repo. The registration writes to `~/.willow/agents.json`, which is picked up by both the dashboard and the `willow_agents` MCP tool at runtime — no core file edits required for local use.

```
willow-dashboard/scripts/register_agent.py
        │
        ▼
~/.willow/agents.json
        │
        ├── willow-dashboard reads at startup
        │       └── agent visible in Settings page
        │       └── WILLOW_AGENT_NAME=name routes chat persona
        │
        └── sap/sap_mcp.py merges at runtime (willow_agents handler)
                └── willow_agents MCP tool returns merged list
                └── agent visible system-wide on this node
```

## Where agents live

**Local override:** `~/.willow/agents.json`
```json
[
  {"name": "nova", "trust": "WORKER", "role": "Exploration, new territory."}
]
```

**System list:** `sap/sap_mcp.py` — the `willow_agents` handler (~line 848).
This is the canonical list for the system. PRs to add permanently.

**MCP tool:** `willow_agents` (app_id required) — returns merged list of system + local agents.

## Registering a new agent (local)

```bash
git clone https://github.com/rudi193-cmd/willow-dashboard
python3 willow-dashboard/scripts/register_agent.py
```

## Registering system-wide (PR)

Add one line to `sap/sap_mcp.py` in the `willow_agents` handler:

```python
{"name": "yourname", "trust": "WORKER", "role": "Your role here."},
```

The registration script prints the exact line.

## SAP auth for new agents

New agents use `app_id` equal to their name for infra-bypass (no PGP required for infra IDs). To create a SAFE-authenticated app instead:

1. Create a SAFE folder under `$WILLOW_SAFE_ROOT/yourname/`
2. Write `manifest.json` + sign with `gpg --detach-sign`
3. The gate will verify on every tool call

See `sap/core/gate.py` for the full auth chain.

---
ΔΣ=42
