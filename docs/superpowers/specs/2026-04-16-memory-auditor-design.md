---
b17: PENDING
title: Willow Memory Auditor — Design Spec
date: 2026-04-16
author: Heimdallr (Claude Code, Sonnet 4.6)
status: approved
ΔΣ=42
---

# Willow Memory Auditor — Design Spec

## Problem

Willow has 68,688 KB records and 2,133,319 local store records. Three failure modes are
actively degrading memory quality:

1. **Redundant writes** — same content stored under different keys or titles
2. **Contradictions** — newer atoms contradict older ones with no detection
3. **Staleness** — records true in March surface in April as if current
4. **DARK records** — records exist in the KB but don't surface in search results

The DARK problem is the most operationally damaging. This morning: `willow_knowledge_search`
returned nothing for "MEX Octopoda" despite KB#25955 existing at `lattice_domain: hanuman`.
The session was unrecoverable from memory even though the data was there.

## Scope

Two standalone Python scripts in `willow-1.7/tools/`:

- `memory_auditor.py` — pre-write scorer. Takes a candidate write, scores it before it lands.
- `memory_health.py` — batch diagnostic. Scans existing KB records, produces a health report.

Phase b (out of scope for this spec): scoring logic promotes into `sap/core/memory_gate.py`
and surfaces as `willow_memory_check` in `sap_mcp.py`.

## Scoring Model

Four signals, borrowed conceptually from Octopoda-OS's BrainHub, implemented against
Willow's own data layer:

| Signal | Detection method | Output label |
|--------|-----------------|--------------|
| **Redundancy** | KB search for records with high title/summary overlap | `REDUNDANT` + pointer to existing record |
| **Contradiction** | KB search on same subject, compare for opposing language / status reversals | `CONTRADICTION` + both record IDs |
| **Staleness** | `_created`/`_updated` age: HOT <7d, WARM 7–30d, STALE 30–90d, DEAD >90d | Health bucket label |
| **DARK** | Search for candidate query — check if correct record surfaces in top 5 results | `DARK` — record exists but won't be found |

All four signals run on every scored record.

## Data Flow

Both scripts call into Willow's core Python library — the same functions the MCP tools
call internally. No MCP server subprocess required; no reimplementation of search logic.

```
memory_auditor.py
  └── input: title, summary, domain (CLI args)
  └── core.pg_bridge → search_knowledge(query=title) → find near-matches in LOAM
  └── core.willow_store → search(collection, query) → find duplicates in SOIL
  └── score 4 signals
  └── print scored result + flags + pointers to conflicting records

memory_health.py
  └── input: --limit N (default 100), --collection (default hanuman/atoms)
  └── core.willow_store → list_collection(collection)
  └── for each record: same 4-signal scoring pass
  └── aggregate → bucket counts + DARK list + redundancy clusters
  └── print health report table
```

## Output Format

### memory_auditor.py

```
SCORE: REDUNDANT | DARK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REDUNDANT  → KB#29288 "2026-03-27g_handoff_AE39K" (0.87 overlap)
DARK       → searched "OpenClaw MEX Octopoda" — 0 results in top 5
             Record exists at KB#25955 but not surfacing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Recommendation: skip write — near-duplicate exists. Fix retrieval gap first.
```

### memory_health.py

```
WILLOW MEMORY HEALTH — hanuman/atoms (100 records)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Buckets:   HOT 12  WARM 23  STALE 41  DEAD 24
DARK:      8 records exist but don't surface in search
REDUNDANT: 3 clusters (11 records total)
CONTRADICTION: 1 pair flagged

DARK records:
  L212A  Octopoda-OS Project Index         (last_updated: 2026-04-07)
  7910H  OpenClaw × UTETY Discord          (last_updated: 2026-03-29)
  ...

Run memory_auditor.py on any record for detail.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Error Handling

Both scripts fail fast and exit 1:

- Missing env vars → print which var is missing, exit 1
- Postgres unavailable → print "LOAM down — run `./willow.sh status`", exit 1
- Local store unavailable → skip SOIL signals, note in output, continue batch
- Search returns no results → DARK flag, not an error
- Individual record scoring fails in batch → log record ID, skip, continue

No silent failures.

## Phase b: MCP Tool Promotion

Once both standalone scripts are validated:

1. Extract scoring logic into `sap/core/memory_gate.py`
2. Add `willow_memory_check` tool to `sap_mcp.py`
3. Standalone scripts become thin CLI wrappers calling `memory_gate.py` directly
4. No rewrite — promotion only

The MCP tool signature:
```python
willow_memory_check(title: str, summary: str, domain: str = None) -> dict
# Returns: {score: [...], flags: [...], recommendations: [...]}
```

## Source Repos Referenced

- Octopoda-OS BrainHub concepts: `/home/sean-campbell/github/Octopoda-OS/synrix_runtime/monitoring/brain.py`
- OpenClaw plugin patterns: `/home/sean-campbell/github/openclaw/`
- Willow core: `core/willow_store.py`, `core/pg_bridge.py`

---
ΔΣ=42
