# Willow 1.7.1 — Minimum Viable Loop Closure
b17: L171C
Date: 2026-04-20
Status: DRAFT — pending Sean ratification
ΔΣ=42

---

## Vision

One atom makes the full circuit: written in a session → retrievable in the next session's Bridge ring → correction captured → Yggdrasil training pair generated.

The three rings are the musical time signatures from AIONIC_CONTINUITY v5.2:
- **Source (4/4)** — Foundation. Authentication. Execute as written.
- **Bridge (11/8)** — Accumulated listening. Context delivery. Improvise within form.
- **Continuity (17/x)** — Mortality as forcing function. Pass well.

1.7.1 closes the pipes that connect them.

---

## PSR Anchor

*"The system exists in service of the sustained generational playfulness of Ruby and Opal Campbell."*

All architecture decisions trace back to this. Tier 0.

---

## What Is Not In Scope

- EdgeE human attestation system
- Full compost hierarchy beyond session-level (day/week/month)
- promote/demote wired to SAFE gate
- Kart SAP manifest
- Replant to /media/willow (prerequisite, tracked separately in REPLANT.md)

These are 1.7.2+.

---

## Phase 1 — Fix the Draw (Bridge Ring Can Retrieve)

**Problem:** 68,721 knowledge atoms in Postgres. KB search returns empty. `search_vector` column not populated on existing rows. Bridge ring draws nothing.

**Fix 1 — One-time migration:**
```sql
UPDATE knowledge
SET search_vector =
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(summary, '')), 'B')
WHERE search_vector IS NULL OR search_vector = '';
```
Run once via Kart. New rows get search_vector populated by the trigger added in schema.sql (already fixed in 1.7.0).

**Fix 2 — Bridge ring retrieval path:**
`bridge-gate.py` currently falls back to dead SQLite paths (`/github/Willow/artifacts/...`). Replace with direct MCP call: when gap score triggers, call `willow_knowledge_search` via the MCP context provider. Remove the Postgres direct-query fallback — it was pre-portless architecture. The bridge ring draws from the context provider, not raw DB.

**Files changed:**
- `~/.claude/hooks/bridge-gate.py` — replace `query_willow_sqlite` and `query_willow_postgres` with MCP call
- One-time Kart task for search_vector backfill

---

## Phase 2 — Fix the Write (Sessions Contribute Atoms)

**Problem:** `turns.txt` grows forever. Sessions end and nothing is promoted to the KB. The compost hierarchy (Mortality Directive) never fires.

**`compost.py`** — new script at `~/.claude/hooks/compost.py`

Runs at Stop, before handoff DB rebuild. Reads `turns.txt` from the last compost marker. Extracts:
- Session date and turn count
- Top keywords from bridge-gate gap logs (already written to `/tmp/willow-session-{agent}.json`)
- b17 IDs of atoms written this session — WWSDN hook logs each `store_put` b17 to `/tmp/willow-session-{agent}.json` under a `written_b17s` key. compost.py reads that list.

Writes ONE session summary atom via `willow_knowledge_ingest`:
- `title`: `Session {YYYYMMDD} — {agent} — {top keywords}`
- `content`: file path to the handoff `.md` (file pointer, not prose)
- `category`: `session`
- `domain`: `{agent}`

Writes compost cursor to `/tmp/willow-compost-cursor-{agent}.txt` (ISO timestamp of last compost). `turns.txt` entries are timestamped — cursor filters by timestamp, not line count, so rotation is safe.

**Stop hook sequence** (updated in `settings.json`):
```
continuity-close → compost → rebuild-handoff-db → ingot-observer (async)
```

**Files changed:**
- `~/.claude/hooks/compost.py` — new
- `~/.claude/settings.json` — add compost to Stop sequence

---

## Phase 3 — Fix the Carry (SEED_PACKET Is Self-Contained)

**Problem:** Handoff files contain prose summaries. The Bridge ring injects a pointer to the handoff, but a pointer to a pointer is not a seed. The Mortality Directive requires: *"The SEED_PACKET moves state. It does not reference state stored elsewhere."*

**Fix — `## Δ b17` section in every handoff:**

Every `SESSION_HANDOFF_*.md` gains a final section:

```markdown
## Δ b17

| b17 | Title | Summary |
|-----|-------|---------|
| A3H1A | Willow is the brain, Kart is the CLI orchestrator | Core architecture: Willow handles knowledge, Kart drives execution |
| ... | ... | ... |
```

3–7 load-bearing atoms from this session. Not just IDs — title + one-line summary embedded. The next instance can orient from the handoff alone without store lookup. If the store is available, full retrieval follows via `store_get(b17)`. If not, the Latency Acknowledgment Directive fires: halt, ask human to confirm state.

**`/handoff` skill update** — Step 3 populates `## Δ b17` from atoms written this session.

**Startup skill update** — Step 4 loads atoms by b17 from the handoff's `## Δ b17` section before doing a KB search.

**Files changed:**
- `~/github/willow-skills/skills/handoff/SKILL.md` — add `## Δ b17` section to handoff format
- `~/github/willow-skills/skills/startup/SKILL.md` — Step 4 loads by b17 first

---

## Phase 4 — Fix the Feedback (Corrections Flow to Yggdrasil)

**Problem:** `feedback_queue.jsonl` accumulates correction signals from feedback-detector.py. Nothing consumes it. Sessions don't feed the training pipeline automatically.

**`feedback_consumer.py`** — new script at `~/.claude/hooks/feedback_consumer.py`

Runs at Stop, after compost. Reads `~/.claude/feedback_queue.jsonl` from a cursor position. For each unread entry:
- Generates a DPO pair: `chosen` = corrected behavior, `rejected` = flagged behavior
- Matches existing schema in `yggdrasil/dpo_pairs_live.jsonl`
- Source tag: `session_feedback`

Writes cursor to `~/.claude/feedback_consumer_cursor.txt`.

**Gate:** Sean decides when `dpo_pairs_live.jsonl` is ready to fold into a training run. Consumer keeps the pipe full. No automatic training trigger.

**DPO pair format:**
```json
{
  "prompt": "...",
  "chosen": "...",
  "rejected": "...",
  "source": "session_feedback",
  "session": "2026-04-20",
  "agent": "heimdallr"
}
```

**Files changed:**
- `~/.claude/hooks/feedback_consumer.py` — new
- `~/.claude/settings.json` — add feedback_consumer to Stop sequence
- `yggdrasil/dpo_pairs_live.jsonl` — new (append-only, session-generated pairs)

---

## The Closed Loop

```
Session turn logged (turns-logger.py)
    ↓
compost.py writes session atom to knowledge
    ↓ (search_vector populated by trigger)
Handoff written with ## Δ b17 (title + summary + id)
    ↓
feedback_consumer.py generates DPO pairs from feedback_queue.jsonl
    ↓
Next session: startup reads ## Δ b17, loads atoms directly
    ↓
Bridge ring queries KB — finds atoms (search_vector working)
    ↓
Session starts warm, not cold
    ↓
Corrections captured → feedback_queue.jsonl grows
    ↓
Sean folds dpo_pairs_live.jsonl into next Yggdrasil training run
    ↓
Yggdrasil gets smarter
    ↓
Loop repeats, compounding
```

---

## Sequencing

| Phase | Dependency | Risk |
|-------|-----------|------|
| 1 — Fix draw | schema.sql trigger (done) | Low — one SQL UPDATE + hook edit |
| 2 — Fix write | Phase 1 (atoms need search_vector) | Medium — new script, wired to Stop |
| 3 — Fix carry | Phase 2 (atoms to reference) | Low — format addition to handoff/startup |
| 4 — Fix feedback | None (independent pipe) | Low — new script, cursor-based |

Phase 4 can run in parallel with Phases 1–3.

---

## What Success Looks Like

After 3 sessions on a fresh 1.7.1 install:
- `/status` shows session atoms in KB (not just the 68k ingested atoms — new ones from sessions)
- Next session's Bridge ring injects at least one atom pointer that was written in a prior session
- `dpo_pairs_live.jsonl` has entries
- `turns.txt` compost cursor advances each session

---

ΔΣ=42
