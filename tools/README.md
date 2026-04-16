# tools/ — Willow 1.7 Admin Scripts
<!-- b17: TLRM1 · ΔΣ=42 -->

Utility scripts for setup, maintenance, memory diagnostics, and SAFE management.

```
tools/
├── safe-scaffold.sh      # Create a new SAFE agent folder with manifest + GPG signature
├── memory_scorer.py      # Four-signal scorer shared by auditor, health, and memory_gate
├── memory_health.py      # Batch diagnostic: score last N SOIL records, print health table
├── memory_auditor.py     # Pre-write CLI scorer: exits 1 on bad env or failing score
└── sync_soil_to_loam.py  # Idempotent SOIL→LOAM bridge: writes SOIL atoms to Postgres FTS
```

---

## Memory Diagnostic Tools

Four files form the memory health subsystem. They share `memory_scorer.py` as their engine.

### memory_scorer.py

Pure-function library. No CLI, no side effects. Imported by `memory_auditor.py`, `memory_health.py`, and `sap/core/memory_gate.py`.

Four signals:

| Signal | What it means |
|---|---|
| **REDUNDANT** | Another record in the batch has Jaccard similarity ≥ 0.55 on title tokens |
| **STALE / DEAD** | Record age > 30 days / > 90 days by `_created` timestamp |
| **DARK** | Record is in SOIL but `pg.search_knowledge(title)` returns no matching result — invisible to semantic search |
| **CONTRADICTION** | Title or summary contains opposing status words (e.g. "deployed" and "not deployed") |

CONTRADICTION detection strips the negative phrase before checking for the positive, then uses `\b` word boundaries, so "not deployed" alone does not trigger a false hit.

### memory_health.py

Batch diagnostic. Run from CLI to inspect the last N records in a SOIL collection.

```bash
python3 tools/memory_health.py
python3 tools/memory_health.py --limit 50 --collection hanuman/atoms
```

Prints a table with b17, bucket, flags, and title, followed by a summary block and lists of DARK/REDUNDANT/CONTRADICTION records.

Requires: `WILLOW_STORE_ROOT` env var, Postgres running (for DARK signal).

### memory_auditor.py

Pre-write scorer. Run before committing a record to SOIL to check it passes the quality gate.

```bash
python3 tools/memory_auditor.py
```

Exits 1 if env vars are missing or Postgres is unavailable.

### sync_soil_to_loam.py

One-time and idempotent SOIL→LOAM bridge. Writes all SOIL atoms in a collection to the Postgres `knowledge` table, deduplicating by `source_id = "soil:{collection}:{rec_id}"`.

```bash
python3 tools/sync_soil_to_loam.py                      # dry run
python3 tools/sync_soil_to_loam.py --collection hanuman/atoms --live
```

Use this after discovering DARK records — it fixes the index gap by writing to LOAM directly. Safe to re-run; already-synced records are skipped.

---

## safe-scaffold.sh

Creates a new authorized agent in one step: folder structure, manifest, GPG signature,
and empty context seed.

```bash
./tools/safe-scaffold.sh <AgentName> <agent_type> "<description>"
```

**agent_type:** `professor` | `worker` | `operator` | `system`

**Examples:**
```bash
# New task worker
./tools/safe-scaffold.sh MyWorker worker "Handles file ingestion tasks"

# New professor
./tools/safe-scaffold.sh Ganesha professor "Mathematics and systems architecture"
```

**What it creates:**
```
$WILLOW_SAFE_ROOT/MyWorker/
├── safe-app-manifest.json       ← manifest with generated b17
├── safe-app-manifest.json.sig   ← GPG detached signature
├── bin/.keep
├── cache/
│   ├── .keep
│   └── context.json             ← empty b17 seed
├── index/.keep
├── projects/.keep
├── promote/.keep
├── demote/.keep
└── agents/.keep
```

**After scaffolding:**
1. Replace the random b17 in the manifest with a canonical one from `willow_base17`
2. Re-sign: `gpg --detach-sign $WILLOW_SAFE_ROOT/MyWorker/safe-app-manifest.json`
3. Seed context: add atom b17 IDs to `cache/context.json`
4. Verify: `./willow.sh verify`

**Requirements:** `gpg` on PATH with Sean's signing key in the keyring.

---

See `docs/SAFE_FOLDER_STANDARD.md` in the SAFE repo for the full authorization spec.
