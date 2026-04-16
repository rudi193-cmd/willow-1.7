# sap/core/ — SAP Pipeline Stages
<!-- b17: SAP0C · ΔΣ=42 -->

The five modules here form the SAP pipeline: authorize → assemble → deliver. Nest intake and classification are a separate pipeline that runs on the same authorization foundation.

```
sap/core/
├── gate.py          # Step 1: PGP authorization
├── context.py       # Step 2: KB context assembly
├── deliver.py       # Step 3: Format for injection
├── nest_intake.py   # File intake pipeline (parallel to gate/context/deliver)
└── classifier.py    # File content classification (used by nest_intake)
```

---

## gate.py — Authorization Gate

The gate is the first check any app must pass. It is stateless — there is no session, no token, no cache. Every call runs the full four-step chain.

### The Four Steps

```
1. SAFE folder exists      $WILLOW_SAFE_ROOT/<app_id>/
2. Manifest present        safe-app-manifest.json
3. Signature present       safe-app-manifest.json.sig
4. GPG verifies            gpg --verify <sig> <manifest>  → exit 0
```

The gate also checks `$WILLOW_SAFE_ROOT/utety-chat/professors/<app_id>/` as a secondary path — this covers professor-specific SAFE entries.

### Public API

```python
from sap.core.gate import authorized, require_authorized, get_manifest, list_authorized

# Boolean check — logs denial if False
ok = authorized("utety-chat")

# Raises PermissionError on denial — preferred for hard gates
require_authorized("utety-chat")

# Load the manifest JSON (runs full auth chain)
manifest = get_manifest("utety-chat")   # returns dict or None

# List all currently-authorized apps (runs gpg for each — use sparingly)
apps = list_authorized()
```

### Logging

All decisions are logged to `sap/log/`:
- Denials → `gaps.jsonl` with `event: "access_denied"` and reason
- Grants → `grants.jsonl` with `event: "access_granted"`

### Revocation

Delete the SAFE folder or its `.sig` file. The gate will deny on the next call. No server restart required, no config change needed.

### Manifest Format

The `safe-app-manifest.json` can carry any data the app needs. The gate reads only `data_streams` (for `context.py`). A minimal manifest:

```json
{
  "app_id": "utety-chat",
  "name": "UTETY Faculty Chat",
  "data_streams": [
    {"id": "knowledge"},
    {"id": "governance"}
  ]
}
```

### GPG Behavior

- `gpg` must be on PATH
- The key that signed the manifests must be in the GPG keyring
- If `gpg` is not found → `"gpg not found on PATH"` denial
- If verification times out (>5s) → `"gpg verify timed out"` denial
- If the server's SAFE root is on a removable drive → unmounting the drive revokes all apps instantly

---

## context.py — Context Assembler

Takes an authorized app ID and a query, returns a dict of KB atoms scoped to the app's permitted data streams.

### How It Works

1. Runs `gate.authorized(app_id)` — returns `None` if denied
2. Reads `manifest["data_streams"]` to get permitted stream IDs
3. Optionally loads `SAFE/<app_id>/cache/context.json` — pre-cached b17 pointers or raw content
4. Queries Postgres for atoms matching the query, filtered by category if `category_filter` is set
5. Returns a dict with `app_id`, `query`, `atoms`, `cache`, `manifest`, `permitted_streams`

### Cache Files

Each authorized app can have a `cache/context.json` at `$WILLOW_SAFE_ROOT/<app_id>/cache/context.json`. Two formats are supported:

**b17 pointer format** — preferred. The cache file references atoms by their BASE 17 ID. The assembler resolves these to full content at assembly time, so the cache stays valid as atoms are updated:
```json
{"b17": ["5AAN0", "H6H23", "K17W0"]}
```

**Raw content format** — simpler. The content is injected directly:
```json
{"content": "Professor context injected verbatim here…"}
```

If neither key is present, the entire file contents are injected as-is.

### Usage

```python
from sap.core.context import assemble

ctx = assemble(
    app_id="utety-chat",
    query="what is the current task",
    max_chars=4000,
    category_filter=["governance", "architecture"],   # optional
    cache_app_id="Oakenscroll",   # load cache from a different app folder
)
# ctx is None if not authorized
```

---

## deliver.py — Context Formatter

Takes the assembled context dict and formats it as a string suitable for prepending to a system prompt.

### Output Format

```
--- SAP CONTEXT: utety-chat ---
app: UTETY Faculty Chat
query: what is the current task
permitted_streams: knowledge, governance

[CACHED CONTEXT]
<up to 2000 chars of cache content>

[KB ATOMS]
[governance/mcp] atom title: summary text here…
[architecture/mcp] another atom: its summary…

--- END SAP CONTEXT ---
```

### Usage

```python
from sap.core.deliver import to_string, to_window

# Get as string for prepending to a system prompt
header = to_string(ctx)     # returns "" if ctx is None (unauthorized)

# Print to stdout (for pipe-based injection into Claude Code)
to_window(ctx)
```

Every call to `to_string` or `to_window` logs a delivery record to `sap/log/deliveries.jsonl`.

---

## nest_intake.py — File Intake Pipeline

The Nest is a staging directory. Sean drops files there. `scan_nest()` classifies each one, matches it against known entities in LOAM, proposes a destination, and stages it for review. Nothing moves until Sean confirms.

This is Dual Commit in practice: the AI proposes, the human ratifies.

### Flow

```
1. scan_nest()       Scan $WILLOW_NEST_DIR for new files
2. stage_file()      Read snippet → classify → match entities → propose path → queue
3. get_queue()       Return all pending items
4. confirm_review()  Sean ratifies → file moves to proposed path + atom ingested to LOAM
   skip_item()       Sean dismisses → file stays in Nest, item marked skipped
```

### Routing Rules

Files are routed to one of two root destinations:

| File type | Destination root |
|---|---|
| Personal (journal, narrative, legal, photos, etc.) | `$WILLOW_FILED_DIR` (`~/Ashokoa/Filed/…`) |
| System (code, architecture, agents, corpus, etc.) | `$WILLOW_PARTITION_DIR/…` (`/media/willow/…`) |

Within system files, project-specific routing matches entity names and filename keywords to known projects (`willow-1.7`, `utety`, `die-namic`, `yggdrasil`, etc.).

### TOS Policy Check

When `classifier.py` labels a file as a legal document (`legal_agreement`, `terms_of_service`, `contract`), `nest_intake.py` runs a TOS policy check against a set of tripwires:

| Rule | Verdict | Triggers on |
|---|---|---|
| `sells_personal_data` | BLOCK | "sell" + "data" or "sell" + "personal" |
| `perpetual_irrevocable` | BLOCK | "perpetual" + "irrevocable" |
| `ai_output_ownership` | BLOCK | "ownership" + "generated", "own" + "output" |
| `arbitration_waiver` | FLAG | "arbitration" |
| `class_action_waiver` | FLAG | "class action" |
| `data_broker_sharing` | FLAG | "partners" + "share" |
| `biometric_collection` | FLAG | "biometric", "facial recognition" |

The verdict is prepended to the proposed summary: `[POLICY:BLOCK] Rules triggered: perpetual_irrevocable`. This surfaces in the review queue so Sean sees it before confirming.

### MCP Tools

```
willow_nest_scan    → scan_nest() + get_queue()
willow_nest_queue   → get_queue()
willow_nest_file    → confirm_review(item_id) or skip_item(item_id)
```

The `override_dest` parameter on `willow_nest_file` lets Sean redirect the file to a different path than proposed.

### Entity Matching

`_match_entities()` searches LOAM's `entities` table for terms from the filename and content snippet. Exact name matches get confidence 0.9; prefix matches get 0.6. The top 10 matches (sorted by confidence × mention count) are stored as JSONB in `nest_review_queue.matched_entities`.

---

## classifier.py — File Classifier

Classifies files by filename and content snippet. Returns `{category, subcategory, summary}`. Used by `nest_intake.stage_file()`.

Classification order:
1. **Agent routing** (hard rule) — detects `FOR <AGENT>`, `TO <AGENT>`, or `CHAIN: A → B → C` patterns
2. **Session handoffs** (hard rule) — filename contains `HANDOFF`
3. **Filename keyword rules** — matches against ~20 keyword lists covering legal, journal, narrative, code, UTETY, media, personal, etc.
4. **Date-named markdown** — `YYYY-MM-DD.md` → journal/daily
5. **Default** — `reference/general`

### Known Categories

```
session, narrative, architecture, research, reference,
corpus, utety, governance, legal, legal_agreement,
terms_of_service, contract, personal, media,
conversation, die-namic, agent, safe, system,
agent_task, agent_chain, journal, handoff, code, specs
```

The taxonomy is authoritative from LOAM (`WILLOW_CATEGORY_MAPPING` knowledge atom) on first call, cached in memory. Falls back to the hardcoded set if LOAM is unavailable.

### Agent Names

The classifier knows 20 named agents for routing detection:
`willow, kart, ada, riggs, steve, shiva, ganesha, oakenscroll, hanz, nova, alexis, ofshield, gerald, mitra, consus, jane, jeles, binder, pigeon, heimdallr`

Files addressed to any of these (by filename or content header) are routed to `agent_task` or `agent_chain` category.
