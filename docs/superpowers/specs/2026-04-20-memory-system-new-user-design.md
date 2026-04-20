# Memory System — New User Install
b17: (assign on commit)  ΔΣ=42

**Date:** 2026-04-20  
**Author:** Heimdallr  
**Goal:** A fresh `seed.py` plant produces a working memory system — per-session handoffs, compost pipeline, KB reads/writes — without manual intervention.

---

## Scope

Three mechanical repairs + a portless migration. No architectural changes. No SAFE root creation (deferred — requires PGP key decision). No `ask()` / LLM routing (out of scope for memory system).

---

## Part 1 — SAFE_ROOT Default (3 files)

**Problem:** `willow.sh`, `safe-scaffold.sh`, and `seed.py` all default `WILLOW_SAFE_ROOT` to `/media/willow/SAFE/Applications` — a partition mount path that does not exist on any machine except Sean's. seed.py Step 7 calls safe-scaffold.sh, so if safe-scaffold.sh fails, app registration silently fails.

**Fix:** Change the default to `${HOME}/SAFE/Applications` in all three files. The env var override still works as before.

| File | Line | Change |
|------|------|--------|
| `willow.sh` | 30 | `${WILLOW_SAFE_ROOT:-/media/willow/SAFE/Applications}` → `${WILLOW_SAFE_ROOT:-${HOME}/SAFE/Applications}` |
| `tools/safe-scaffold.sh` | 27 | same pattern |
| `willow-seed/seed.py` | `step_safe()` | `partition_safe = "/media/willow/SAFE/Applications"` → `str(Path.home() / "SAFE" / "Applications")` — remove dead `startswith("/media/willow")` branch |

---

## Part 2 — safe_integration.py Portless Migration (15 repos)

**Problem:** Every `safe-app-*` repo has a `safe_integration.py` that calls `localhost:8420` (the old HTTP porch). The porch is removed. All `query()`, `status()`, and `ask()` calls are dead on any machine running willow-1.7. The `_APP_DATA` path is hardcoded to `/media/willow/Apps/<app>` — a Windows partition path.

**Fix:** Replace HTTP calls with direct SOIL SQLite reads (stdlib only — no new dependencies). Fix `_APP_DATA` to a user-space XDG path.

### Migration pattern

```python
# Remove:
import requests as _requests
_WILLOW_URL = _os.environ.get("WILLOW_URL", "http://localhost:8420")
_PIGEON_URL = f"{_WILLOW_URL}/api/pigeon/drop"

# Add:
import sqlite3
_STORE_ROOT = Path(_os.environ.get("WILLOW_STORE_ROOT",
                   str(Path.home() / ".willow" / "store")))
```

```python
# _APP_DATA — was:
_APP_DATA = Path("/media/willow/Apps/utety-chat")  # varies per app
# becomes:
_APP_DATA = Path.home() / ".willow" / "apps" / _APP_ID
```

### Function-by-function changes

| Function | Before | After |
|----------|--------|-------|
| `query(q, limit)` | POST to Pigeon bus | Direct SQLite read from `$STORE_ROOT/knowledge/store.db` |
| `contribute(content, ...)` | POST to Pigeon bus | Already filesystem — fix `_APP_DATA` path only |
| `status()` | GET to porch | Check `$STORE_ROOT` dir + `knowledge/store.db` readable |
| `ask(prompt, ...)` | POST to porch | Graceful degradation — returns `"[Willow LLM routing not available in portless mode]"` |
| `get_consent_status()` | GET to porch | Returns `False` (graceful degradation — consent UI deferred) |
| `request_consent_url()` | Returns porch URL | Returns `None` |
| `check_inbox()` | GET to porch | Returns `[]` |
| `send()` | POST to porch | Returns `{"ok": False, "error": "messaging deferred"}` |
| `_drop()` | Internal HTTP helper | Remove entirely |

### New `query()` implementation

```python
def query(q: str, limit: int = 5) -> list:
    db_path = _STORE_ROOT / "knowledge" / "store.db"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT data FROM records WHERE deleted=0 AND data LIKE ? LIMIT ?",
            (f"%{q}%", limit)
        ).fetchall()
        conn.close()
        return [json.loads(r[0]) for r in rows]
    except Exception:
        return []
```

### New `status()` implementation

```python
def status() -> dict:
    db_path = _STORE_ROOT / "knowledge" / "store.db"
    reachable = db_path.exists()
    return {"ok": reachable, "store": str(_STORE_ROOT), "mode": "portless"}
```

### Repos affected

16 canonical `safe-app-*` repos (the `safe-apps/` directory is a duplicate clone with the same GitHub remotes — pushing to canonicals covers it):

`dating-wellbeing`, `game`, `the-squirrel`, `llmphysics-bot`, `field-notes`, `ask-jeles`, `public-ledger`, `private-ledger`, `source-trail`, `grove`, `the-binder`, `utety-chat`, `genealogy`, `nasa-archive`, `UTETY-Reddit-Bots`, `law-gazelle`

Note: `safe-app-law-gazelle` has `safe_integration.py` in both the repo root and `src/`. Both copies get migrated; the root copy is likely a leftover from a refactor.

**Implementation approach:** produce one canonical migrated template, apply mechanically per repo (only `_APP_ID` differs), one commit per repo.

---

## Part 3 — Flag Resolution

### Resolve immediately (stale — code already correct)

| Flag | Evidence |
|------|----------|
| `schema.sql outdated — wrong table names` | schema.sql uses `knowledge`, `knowledge_edges`, `kart_task_queue` — correct |
| `seed.py has no Step 7` | `step_register_apps()` fully implemented |
| `safe-scaffold.sh title-cases app_id` | Line 43: `AGENT_TITLE="${AGENT_NAME}"` with explicit comment |
| `willow-dashboard CLAUDE.md no persona/app_id` | CLAUDE.md explicitly wires identity to `WILLOW_AGENT_NAME` env var |
| `bridge-gate.py inserts to journal_events (table missing)` | bridge-gate.py not in hooks; `journal_events` exists in schema.sql |
| `Stop hook builds HANUMAN handoff DB` | willow-1.7 `.claude/settings.json` sets `WILLOW_AGENT_NAME=heimdallr` |
| `Global WILLOW_STORE_ROOT wrong store` | `~/.willow/store` IS the live store (2.1M records); the flag itself was wrong |

### Resolve after implementation commits

| Flag | Closes when |
|------|-------------|
| `All safe_integration.py use HTTP porch` | After 15 repo migration commits |
| `willow.sh WILLOW_SAFE_ROOT defaults to partition path` | After willow.sh + safe-scaffold.sh + seed.py commits |

---

## Out of Scope (this stack)

- SAFE root creation + PGP fingerprint wiring (requires key decision)
- `ask()` / LLM routing (separate concern from memory system)
- `credentials.json` plaintext keys (separate security task)
- `safe-app-vision-board` FastAPI port 8420 violation (separate migration)
- Uncomposted session backlog (separate archaeology task)
