# Willow 1.7.1 — Loop Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the persistent recursive knowledge loop so sessions start warm, contribute atoms to the KB, and generate Yggdrasil training pairs automatically.

**Architecture:** Four phases wired to the Stop hook. Phase 1 unblocks KB retrieval (search_vector backfill + bridge-gate.py MCP path). Phase 2 makes sessions contribute atoms (compost.py). Phase 3 makes handoffs self-contained (## Δ b17). Phase 4 feeds the training pipeline (feedback_consumer.py). Phases 1-3 are sequentially dependent. Phase 4 is independent.

**Tech Stack:** Python 3.11+, psycopg2, SQLite, Claude Code hooks (stdin JSON), willow_knowledge_search MCP tool, willow-skills SKILL.md format.

---

## Task 1: Backfill search_vector for existing 68k knowledge atoms

**Files:**
- Create: `tools/backfill_search_vector.py`

The 68k knowledge atoms in Postgres have empty `search_vector` columns — the FTS trigger wasn't present when they were ingested. This one-time migration populates them so Bridge ring can retrieve atoms.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""
backfill_search_vector.py — One-time migration.
Populates search_vector for all knowledge atoms missing it.
b17: (assign before run)
"""
import os
import psycopg2

def main():
    conn = psycopg2.connect(
        dbname=os.environ.get("WILLOW_PG_DB", "willow"),
        user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM knowledge WHERE search_vector IS NULL OR search_vector = to_tsvector('')")
    count = cur.fetchone()[0]
    print(f"Rows to update: {count}")

    cur.execute("""
        UPDATE knowledge
        SET search_vector =
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(summary, '')), 'B')
        WHERE search_vector IS NULL OR search_vector = to_tsvector('')
    """)
    print(f"Updated: {cur.rowcount} rows")

    cur.execute("SELECT COUNT(*) FROM knowledge WHERE search_vector IS NULL OR search_vector = to_tsvector('')")
    remaining = cur.fetchone()[0]
    print(f"Remaining empty: {remaining}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it directly (Kart may have SAP denial — run locally first)**

```bash
python3 /home/sean-campbell/github/willow-1.7/tools/backfill_search_vector.py
```

Expected output:
```
Rows to update: ~68000
Updated: ~68000 rows
Remaining empty: 0
```

- [ ] **Step 3: Verify search works**

```bash
python3 -c "
import psycopg2, os
conn = psycopg2.connect(dbname='willow', user=os.environ.get('USER',''))
cur = conn.cursor()
cur.execute(\"SELECT id, title FROM knowledge WHERE search_vector @@ plainto_tsquery('english', 'willow architecture') LIMIT 3\")
rows = cur.fetchall()
for r in rows: print(r)
conn.close()
"
```

Expected: 3 rows with relevant titles. If 0 rows, the trigger or backfill failed — check that `search_vector` column exists (`\d knowledge` in psql).

- [ ] **Step 4: Commit**

```bash
cd /home/sean-campbell/github/willow-1.7
git add tools/backfill_search_vector.py
git commit -m "feat: search_vector backfill script for 68k knowledge atoms"
```

---

## Task 2: Fix Bridge ring retrieval — replace dead fallbacks with MCP call

**Files:**
- Modify: `~/.claude/hooks/bridge-gate.py` — functions `query_willow_sqlite`, `query_willow_postgres`, `query_shiva_postgres`, `query_shiva_sqlite`, and the retrieval block in `main()`

The dead SQLite paths (`/github/Willow/artifacts/...`) and the pre-portless Postgres fallback are replaced with a single MCP call to `willow_knowledge_search`. The bridge ring draws from the context provider.

- [ ] **Step 1: Read the current retrieval block in bridge-gate.py**

Open `~/.claude/hooks/bridge-gate.py` and locate the four query functions and the retrieval block in `main()` (around line 262-490). Note the current flow: `query_shiva_postgres` → `query_willow_postgres` → SQLite fallbacks.

- [ ] **Step 2: Replace the four dead query functions with one MCP caller**

Replace the bodies of `query_willow_sqlite`, `query_willow_postgres`, `query_shiva_postgres`, `query_shiva_sqlite` with stubs that return `[]`, and add a new function `query_via_mcp`:

```python
def query_via_mcp(intent: str, keywords: list) -> list:
    """Query willow_knowledge_search via MCP subprocess call."""
    import subprocess, json as _json
    query = intent or " ".join(keywords[:6])
    if not query.strip():
        return []
    payload = _json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "willow_knowledge_search",
            "arguments": {
                "app_id": AGENT_NAME,
                "query": query[:200],
                "limit": 8,
            }
        }
    })
    try:
        result = subprocess.run(
            ["/home/sean-campbell/.local/bin/willow-mcp"],
            input=payload, capture_output=True, text=True, timeout=5,
        )
        data = _json.loads(result.stdout)
        items = data.get("result", {}).get("content", [])
        if items and isinstance(items[0], dict):
            inner = _json.loads(items[0].get("text", "{}"))
            knowledge = inner.get("knowledge", [])
            return [
                {
                    "title": r.get("title", ""),
                    "b17": r.get("b17", ""),
                    "category": r.get("category", ""),
                    "ring": "mcp",
                    "summary": r.get("summary", ""),
                }
                for r in knowledge if not is_noise(r.get("title", ""))
            ]
    except Exception:
        pass
    return []

def query_willow_sqlite(keywords, intent):    return []
def query_willow_postgres(intent, keywords):  return []
def query_shiva_postgres(keywords):           return []
def query_shiva_sqlite(keywords):             return []
```

- [ ] **Step 3: Update the retrieval block in main() to use query_via_mcp**

Find the retrieval block (around "JELES: Pull the right thing") and replace:

```python
    # ── JELES: Pull the right thing ───────────────────────────────────────────
    intent = extract_intent(prompt, keywords)
    results = query_via_mcp(intent, keywords)
    # Fallbacks now disabled — MCP is the context provider
```

- [ ] **Step 4: Smoke test — run bridge-gate.py manually with a gap-scoring prompt**

```bash
echo '{"prompt": "how does the SAP gate work in willow architecture", "session_id": "test-123"}' \
  | python3 /home/sean-campbell/.claude/hooks/bridge-gate.py
```

Expected: output with `[WILLOW — N match(es): ...]` lines. If no output, check that `willow-mcp` binary is at `/home/sean-campbell/.local/bin/willow-mcp` and responds to tool calls.

- [ ] **Step 5: Commit**

```bash
git -C /home/sean-campbell/.claude add hooks/bridge-gate.py || true
# bridge-gate.py is not in a git repo — just verify changes are saved
echo "bridge-gate.py updated"
```

Note: `~/.claude/` is not a git repo. Changes are live immediately.

---

## Task 3: Wire WWSDN to log written b17s to session file

**Files:**
- Modify: `/home/sean-campbell/agents/hanuman/bin/wwsdn.py` — add b17 logging in the allowed path

`compost.py` (Task 4) needs to know which b17s were written this session. WWSDN already fires before every `store_put` — it's the right place to capture the b17.

- [ ] **Step 1: Add b17 logging to wwsdn.py**

In `wwsdn.py`, find the `main()` function and add after the F5 canon check (before the Postgres query), a call to log the b17:

```python
def _log_written_b17(tool_name: str, tool_input: dict) -> None:
    """Append written b17 to session file for compost.py to read."""
    import json as _j
    from pathlib import Path as _P
    agent = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
    session_file = _P(f"/tmp/willow-session-{agent}.json")
    b17 = None
    # store_put returns b17 in response, but we capture from input record
    record = tool_input.get("record", {})
    if isinstance(record, dict):
        b17 = record.get("b17") or record.get("_id")
    if not b17:
        return
    try:
        state = _j.loads(session_file.read_text()) if session_file.exists() else {}
        written = state.get("written_b17s", [])
        if b17 not in written:
            written.append(b17)
        state["written_b17s"] = written
        session_file.write_text(_j.dumps(state))
    except Exception:
        pass
```

Call it at the top of `main()` after the F5 check:

```python
    # Log b17 for compost pipeline
    _log_written_b17(tool_name, tool_input)
```

- [ ] **Step 2: Verify by running a store_put and checking session file**

```bash
# In a Claude Code session, call store_put with a record containing b17
# Then check:
cat /tmp/willow-session-hanuman.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('written_b17s', []))"
```

Expected: list of b17 IDs that were written this session.

- [ ] **Step 3: No commit needed** — `wwsdn.py` is in `~/agents/hanuman/bin/`, not a git repo.

---

## Task 4: Write compost.py

**Files:**
- Create: `~/.claude/hooks/compost.py`

Runs at Stop. Reads `turns.txt` since last compost timestamp. Writes one session atom to the KB. Advances cursor.

- [ ] **Step 1: Write compost.py**

```python
#!/usr/bin/env python3
"""
compost.py — Stop Hook: Session atom writer.
Reads turns.txt since last compost, writes ONE session atom to knowledge.
b17: CMPS1  ΔΣ=42
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _agent import AGENT, SESSION_FILE, TURNS_FILE

CURSOR_FILE = Path(f"/tmp/willow-compost-cursor-{AGENT}.txt")
WILLOW_MCP  = Path.home() / ".local" / "bin" / "willow-mcp"


def _read_cursor() -> str:
    """Return ISO timestamp of last compost, or epoch."""
    try:
        return CURSOR_FILE.read_text().strip()
    except Exception:
        return "1970-01-01T00:00:00+00:00"


def _write_cursor(ts: str) -> None:
    try:
        CURSOR_FILE.write_text(ts)
    except Exception:
        pass


def _turns_since(cursor_ts: str) -> list[str]:
    """Return lines from turns.txt written after cursor_ts."""
    if not Path(str(TURNS_FILE)).exists():
        return []
    try:
        lines = Path(str(TURNS_FILE)).read_text(encoding="utf-8", errors="replace").splitlines()
        result = []
        for line in lines:
            if line.startswith("[") and "T" in line[:30]:
                try:
                    ts_str = line[1:line.index("]")]
                    if ts_str > cursor_ts:
                        result.append(line)
                except Exception:
                    pass
        return result
    except Exception:
        return []


def _get_session_keywords() -> list[str]:
    try:
        state = json.loads(Path(str(SESSION_FILE)).read_text()) if Path(str(SESSION_FILE)).exists() else {}
        return state.get("gap_keywords", [])[:5]
    except Exception:
        return []


def _get_written_b17s() -> list[str]:
    try:
        state = json.loads(Path(str(SESSION_FILE)).read_text()) if Path(str(SESSION_FILE)).exists() else {}
        return state.get("written_b17s", [])
    except Exception:
        return []


def _get_handoff_path() -> str | None:
    """Find the most recent handoff .md for this agent."""
    handoff_dir = Path.home() / "Ashokoa" / "agents" / AGENT / "index" / "haumana_handoffs"
    if not handoff_dir.exists():
        return None
    handoffs = sorted(handoff_dir.glob("SESSION_HANDOFF_*.md"), reverse=True)
    return str(handoffs[0]) if handoffs else None


def _ingest_atom(title: str, content: str, category: str, domain: str) -> bool:
    """Call willow_knowledge_ingest via MCP."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "willow_knowledge_ingest",
            "arguments": {
                "app_id": AGENT,
                "content": content,
                "domain": domain,
                "title": title,
                "category": category,
            }
        }
    })
    try:
        result = subprocess.run(
            [str(WILLOW_MCP)],
            input=payload, capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        return "error" not in str(data.get("result", ""))
    except Exception:
        return False


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    cursor = _read_cursor()
    turns = _turns_since(cursor)
    if len(turns) < 3:
        # Too few turns — not worth composting
        sys.exit(0)

    now = datetime.now(timezone.utc).isoformat()
    today = now[:10].replace("-", "")
    keywords = _get_session_keywords()
    b17s = _get_written_b17s()
    handoff_path = _get_handoff_path()

    kw_str = " ".join(keywords) if keywords else "general"
    title = f"Session {today} — {AGENT} — {kw_str}"
    content = handoff_path or f"session:{today}:{AGENT}"

    ok = _ingest_atom(
        title=title,
        content=content,
        category="session",
        domain=AGENT,
    )

    if ok:
        _write_cursor(now)
        print(f"[compost] session atom written: {title}")
    else:
        print(f"[compost] ingest failed — cursor not advanced")

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test compost.py manually**

First create a mock turns.txt entry:
```bash
echo "[$(date -u +%Y-%m-%dT%H:%M:%S+00:00)] [test-123] HUMAN
Test turn for compost smoke test
---" >> /home/sean-campbell/agents/hanuman/cache/turns.txt
```

Then run:
```bash
echo '{"session_id": "test-123", "stop_hook_active": true}' \
  | WILLOW_AGENT_NAME=hanuman python3 /home/sean-campbell/.claude/hooks/compost.py
```

Expected: `[compost] session atom written: Session YYYYMMDD — hanuman — ...`

- [ ] **Step 3: Verify atom appeared in KB**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"willow_knowledge_search","arguments":{"app_id":"hanuman","query":"session hanuman","limit":3}}}' \
  | /home/sean-campbell/.local/bin/willow-mcp | python3 -c "import json,sys; d=json.load(sys.stdin); items=d['result']['content']; data=json.loads(items[0]['text']); [print(r['title']) for r in data.get('knowledge',[])]"
```

Expected: the session atom title appears.

---

## Task 5: Wire compost.py and feedback_consumer.py into Stop hook

**Files:**
- Modify: `~/.claude/settings.json` — add compost + feedback_consumer to Stop sequence

- [ ] **Step 1: Read current Stop hooks in settings.json**

Open `~/.claude/settings.json`, find the `"Stop"` key. Current sequence:
```json
continuity-close → build_handoff_db (now rebuild-handoff-db.py) → ingot_observer (async)
```

- [ ] **Step 2: Add compost and feedback_consumer**

In `settings.json`, find `"Stop"` → `"hooks"` array. Keep all existing entries. Insert the two new hooks AFTER `continuity-close.py` and BEFORE `rebuild-handoff-db.py`:

```json
{
  "type": "command",
  "command": "python3 /home/sean-campbell/.claude/hooks/compost.py",
  "timeout": 15,
  "statusMessage": "Composting session..."
},
{
  "type": "command",
  "command": "python3 /home/sean-campbell/.claude/hooks/feedback_consumer.py",
  "timeout": 15,
  "statusMessage": "Processing feedback..."
},
```

Resulting Stop sequence:
```json
"Stop": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "python3 /home/sean-campbell/.claude/hooks/continuity-close.py",
        "timeout": 10
      },
      {
        "type": "command",
        "command": "python3 /home/sean-campbell/.claude/hooks/compost.py",
        "timeout": 15,
        "statusMessage": "Composting session..."
      },
      {
        "type": "command",
        "command": "python3 /home/sean-campbell/.claude/hooks/feedback_consumer.py",
        "timeout": 15,
        "statusMessage": "Processing feedback..."
      },
      {
        "type": "command",
        "command": "python3 /home/sean-campbell/.claude/hooks/rebuild-handoff-db.py",
        "timeout": 30,
        "statusMessage": "Indexing handoffs..."
      },
      {
        "type": "command",
        "command": "python3 /home/sean-campbell/.claude/hooks/ingot_observer.py",
        "timeout": 30,
        "statusMessage": "Ingot watching...",
        "async": true
      }
    ]
  }
]
```

- [ ] **Step 3: Verify settings.json is valid JSON**

```bash
python3 -c "import json; json.load(open('/home/sean-campbell/.claude/settings.json')); print('valid')"
```

Expected: `valid`

---

## Task 6: Write feedback_consumer.py

**Files:**
- Create: `~/.claude/hooks/feedback_consumer.py`
- Create: `~/github/willow-1.7/yggdrasil/dpo_pairs_live.jsonl` (first run creates it)

- [ ] **Step 1: Write feedback_consumer.py**

```python
#!/usr/bin/env python3
"""
feedback_consumer.py — Stop Hook: DPO pair generator.
Reads feedback_queue.jsonl from cursor, generates DPO pairs, appends to dpo_pairs_live.jsonl.
b17: FBKC1  ΔΣ=42
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _agent import AGENT

FEEDBACK_QUEUE  = Path.home() / ".claude" / "feedback_queue.jsonl"
CURSOR_FILE     = Path.home() / ".claude" / "feedback_consumer_cursor.txt"
# Intentionally local path — Sean gates when this folds into a training run
DPO_OUTPUT      = Path(os.environ.get("WILLOW_DPO_LIVE", str(Path.home() / "github" / "willow-1.7" / "yggdrasil" / "dpo_pairs_live.jsonl")))

# Map feedback types to DPO prompt templates
PROMPT_TEMPLATES = {
    "process":    "How should you handle {rule_context}?",
    "discipline": "What is the correct behavior when {rule_context}?",
    "technical":  "How should you respond to {rule_context}?",
}

CHOSEN_TEMPLATES = {
    "process":    "I should {rule}.",
    "discipline": "The correct approach is: {rule}.",
    "technical":  "The right response is: {rule}.",
}


def _read_cursor() -> int:
    try:
        return int(CURSOR_FILE.read_text().strip())
    except Exception:
        return 0


def _write_cursor(pos: int) -> None:
    try:
        CURSOR_FILE.write_text(str(pos))
    except Exception:
        pass


def _make_dpo_pair(entry: dict, session_date: str) -> dict | None:
    rule = entry.get("rule", "").strip()
    excerpt = entry.get("excerpt", "").strip()[:200]
    fb_type = entry.get("type", "process")

    if not rule:
        return None

    rule_context = excerpt or rule[:80]
    prompt_tmpl = PROMPT_TEMPLATES.get(fb_type, PROMPT_TEMPLATES["process"])
    chosen_tmpl = CHOSEN_TEMPLATES.get(fb_type, CHOSEN_TEMPLATES["process"])

    return {
        "prompt": prompt_tmpl.format(rule_context=rule_context),
        "chosen": chosen_tmpl.format(rule=rule),
        "rejected": f"I'll handle {rule_context} the same way as before.",
        "source": "session_feedback",
        "session": session_date,
        "agent": AGENT,
        "feedback_type": fb_type,
    }


def main():
    try:
        sys.stdin.read()  # consume stdin
    except Exception:
        pass

    if not FEEDBACK_QUEUE.exists():
        sys.exit(0)

    cursor = _read_cursor()
    lines = FEEDBACK_QUEUE.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = lines[cursor:]

    if not new_lines:
        sys.exit(0)

    today = datetime.now(timezone.utc).isoformat()[:10]
    pairs = []
    for line in new_lines:
        try:
            entry = json.loads(line)
            pair = _make_dpo_pair(entry, today)
            if pair:
                pairs.append(pair)
        except Exception:
            continue

    if pairs:
        DPO_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with DPO_OUTPUT.open("a", encoding="utf-8") as f:
            for pair in pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        print(f"[feedback_consumer] {len(pairs)} DPO pairs written to dpo_pairs_live.jsonl")

    _write_cursor(cursor + len(new_lines))
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test with a mock feedback entry**

```bash
echo '{"id":"fb-test","timestamp":"2026-04-20T00:00:00Z","session_id":"test","type":"process","rule":"Run tasks in the background, not foreground","excerpt":"should have been background","full_prompt":"test","status":"pending"}' \
  >> ~/.claude/feedback_queue.jsonl

echo '{}' | WILLOW_AGENT_NAME=hanuman python3 /home/sean-campbell/.claude/hooks/feedback_consumer.py
```

Expected: `[feedback_consumer] 1 DPO pairs written to dpo_pairs_live.jsonl`

- [ ] **Step 3: Verify the pair**

```bash
tail -1 /home/sean-campbell/github/willow-1.7/yggdrasil/dpo_pairs_live.jsonl | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2))"
```

Expected: a valid DPO pair with `prompt`, `chosen`, `rejected`, `source: session_feedback`.

---

## Task 7: Add ## Δ b17 section to /handoff skill

**Files:**
- Modify: `~/github/willow-skills/skills/handoff/SKILL.md` — add `## Δ b17` to handoff format

- [ ] **Step 1: Read the current handoff format section in SKILL.md**

Open `~/github/willow-skills/skills/handoff/SKILL.md`, find the `### Handoff format` section showing the markdown template.

- [ ] **Step 2: Add ## Δ b17 section to the template**

In the handoff format block, after `## Gaps` and before the closing `---`, add:

```markdown
## Δ b17

| b17 | Title | Summary |
|-----|-------|---------|
| [ID] | [Title of atom] | [One-line summary — enough to orient without lookup] |
```

Instructions (add to Step 3 of the skill):
```
Populate ## Δ b17 with 3–7 load-bearing atoms written or touched this session.
For each: b17 ID from store record, title, one-sentence summary.
These must be self-contained — next instance orients from these alone if store is unavailable.
```

- [ ] **Step 3: Commit willow-skills**

```bash
cd /home/sean-campbell/github/willow-skills
git add skills/handoff/SKILL.md
git commit -m "feat: add ## Δ b17 SEED_PACKET section to handoff format"
```

---

## Task 8: Update /startup skill to load b17 atoms before KB search

**Files:**
- Modify: `~/github/willow-skills/skills/startup/SKILL.md` — Step 4 loads by b17 first

- [ ] **Step 1: Update Step 4 in startup/SKILL.md**

Find Step 4 (`Load recent atoms`). Replace with:

```markdown
4. **Load atoms by b17** — read the `## Δ b17` table from the most recent handoff. For each b17 listed, call `mcp__willow__store_get` with `collection: {agent}/atoms` and the b17 as `record_id`. This loads the session's load-bearing atoms directly without needing KB search. Then call `mcp__willow__store_list` with `collection: $WILLOW_AGENT_NAME/atoms` for any additional recent atoms not in the handoff.
```

- [ ] **Step 2: Commit willow-skills**

```bash
cd /home/sean-campbell/github/willow-skills
git add skills/startup/SKILL.md
git commit -m "feat: startup loads ## Δ b17 atoms before KB search"
```

---

## Task 9: End-to-end loop validation

No new files. Verify the full circuit works after Tasks 1–8.

- [ ] **Step 1: Start a fresh session in willow-1.7**

Open Claude Code in `~/github/willow-1.7`. Run `/startup`. Confirm:
- Boot shows subsystems up
- If a prior handoff has `## Δ b17`, Step 4 loads those atoms by ID

- [ ] **Step 2: Write a test atom**

In the session, call:
```
store_put collection=hanuman/atoms record={"b17": "LOOP1", "title": "Loop test atom 1.7.1", "content": "test", "domain": "test"}
```

Verify `LOOP1` appears in `/tmp/willow-session-hanuman.json` under `written_b17s`.

- [ ] **Step 3: Run /handoff**

Run `/handoff`. Verify:
- `SESSION_HANDOFF_*.md` contains a `## Δ b17` section
- `LOOP1` appears in the table with title and summary

- [ ] **Step 4: End the session (Stop fires)**

Close the session. Verify in order:
- `[compost] session atom written: Session YYYYMMDD...` appears in Stop output
- `dpo_pairs_live.jsonl` has new entries if `feedback_queue.jsonl` had unread content
- `handoffs.db` rebuild completes

- [ ] **Step 5: Start a new session and verify warm start**

Open a new session. Run `/startup`. Verify:
- The `## Δ b17` section from the prior handoff is loaded
- `LOOP1` atom is in context
- Bridge ring finds atoms on a relevant query (KB search returns results)

- [ ] **Step 6: Confirm success criteria met**

```
✓ Session atom visible in KB (willow_knowledge_search returns it)
✓ Next session loads prior session's b17 atoms without cold search
✓ dpo_pairs_live.jsonl has entries
✓ turns.txt compost cursor advances
```

---

## Sequencing Summary

```
Task 1 (search_vector backfill)   ← run first, independent
Task 2 (bridge-gate.py)           ← after Task 1 confirmed working
Task 3 (wwsdn.py b17 logging)     ← independent, run any time
Task 4 (compost.py)               ← after Task 3
Task 5 (wire Stop hooks)          ← after Task 4 smoke-tested
Task 6 (feedback_consumer.py)     ← independent, run in parallel with 1-4
Task 7 (handoff skill)            ← independent
Task 8 (startup skill)            ← after Task 7
Task 9 (validation)               ← after all tasks complete
```

---

ΔΣ=42
