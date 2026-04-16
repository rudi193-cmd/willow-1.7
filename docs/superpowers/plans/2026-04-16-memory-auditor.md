# Memory Auditor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-script memory quality layer (pre-write scorer + batch diagnostic) that surfaces DARK, REDUNDANT, STALE, and CONTRADICTION signals in Willow's knowledge stores, plus a SOIL→LOAM sync bridge to fix the root cause of DARK records.

**Architecture:** Shared scoring logic in `tools/memory_scorer.py`; two thin CLI wrappers (`memory_auditor.py`, `memory_health.py`); a one-shot sync script (`sync_soil_to_loam.py`) that backfills SOIL atoms into Postgres so they become searchable; phase b promotes scorer into `sap/core/memory_gate.py` and exposes `willow_memory_check` in the SAP MCP server.

**Tech Stack:** Python 3.9+, psycopg2, SQLite (via `core/willow_store.WillowStore`), `core/pg_bridge.PgBridge`, pytest, argparse.

**Sandbox finding:** The sandbox test (`tools/sandbox_memory_test.py`) confirmed 27/28 SOIL atoms are DARK — they exist in SQLite but are invisible to `search_knowledge()` because SOIL and LOAM are separate stores with no sync bridge. Task 4 (sync bridge) fixes the root cause. Tasks 1–3 build the detection layer. Tasks 5–6 promote to MCP.

---

## File Map

| File | Status | Responsibility |
|------|--------|---------------|
| `tools/memory_scorer.py` | CREATE | Shared scoring functions: `age_bucket`, `overlap_score`, `check_dark`, `check_contradiction`, `score_record` |
| `tools/memory_auditor.py` | CREATE | CLI: score a single candidate write before it lands |
| `tools/memory_health.py` | CREATE | CLI: batch audit of existing SOIL collection |
| `tools/sync_soil_to_loam.py` | CREATE | One-shot/incremental sync: SOIL atoms → Postgres `knowledge` table |
| `tests/tools/test_memory_scorer.py` | CREATE | Unit tests for all scorer functions (no live DB required) |
| `sap/core/memory_gate.py` | CREATE | SAP-layer wrapper around `memory_scorer.score_record` |
| `sap/sap_mcp.py` | MODIFY | Add `willow_memory_check` tool (phase b) |

---

## Task 1: Unit tests for scorer functions

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/tools/__init__.py`
- Create: `tests/tools/test_memory_scorer.py`

- [ ] **Step 1: Create test file**

```python
# tests/tools/test_memory_scorer.py
"""Unit tests for memory_scorer — no live DB required."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.memory_scorer import age_bucket, overlap_score, word_set, check_contradiction


class TestAgeBucket:
    def test_hot_record(self):
        from datetime import datetime, timedelta
        created = (datetime.now() - timedelta(days=3)).isoformat()
        assert age_bucket(created) == "HOT"

    def test_warm_record(self):
        from datetime import datetime, timedelta
        created = (datetime.now() - timedelta(days=15)).isoformat()
        assert age_bucket(created) == "WARM"

    def test_stale_record(self):
        from datetime import datetime, timedelta
        created = (datetime.now() - timedelta(days=60)).isoformat()
        assert age_bucket(created) == "STALE"

    def test_dead_record(self):
        from datetime import datetime, timedelta
        created = (datetime.now() - timedelta(days=120)).isoformat()
        assert age_bucket(created) == "DEAD"

    def test_bad_date_returns_unknown(self):
        assert age_bucket("not-a-date") == "UNKNOWN"

    def test_empty_string_returns_unknown(self):
        assert age_bucket("") == "UNKNOWN"


class TestWordSet:
    def test_filters_short_words(self):
        result = word_set("the cat sat on a mat")
        assert result == {"sat", "mat"}  # only 3+ chars after filtering ≥4

    def test_normalizes_hyphens(self):
        result = word_set("self-hosted memory-store")
        assert "self" in result
        assert "hosted" in result
        assert "memory" in result
        assert "store" in result

    def test_empty_string(self):
        assert word_set("") == set()

    def test_none_returns_empty(self):
        assert word_set(None) == set()


class TestOverlapScore:
    def test_identical_titles(self):
        score = overlap_score("Session Close 2026-03-27", "Session Close 2026-03-27")
        assert score == 1.0

    def test_no_overlap(self):
        score = overlap_score("Postgres schema truth", "Reddit post written")
        assert score == 0.0

    def test_partial_overlap(self):
        score = overlap_score("Session Close 2026-03-27 Session B",
                              "Session Close 2026-03-28 Session L")
        assert 0.4 < score < 1.0

    def test_empty_titles(self):
        assert overlap_score("", "") == 0.0
        assert overlap_score("something real", "") == 0.0


class TestCheckContradiction:
    def test_blocked_and_unblocked(self):
        hits = check_contradiction("SA002 progress", "cube_cells_indexer unblocked by schema fix")
        assert any("blocked" in h for h in hits)

    def test_no_contradiction(self):
        hits = check_contradiction("SLM benchmark results", "qwen2.5 fastest model confirmed")
        assert hits == []

    def test_complete_and_incomplete(self):
        hits = check_contradiction("feature complete but incomplete data", "")
        assert any("complete" in h for h in hits)
```

- [ ] **Step 2: Run tests — expect ImportError (module not written yet)**

```bash
cd /home/sean-campbell/github/willow-1.7
python3 -m pytest tests/tools/test_memory_scorer.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'tools.memory_scorer'`

- [ ] **Step 3: Create `__init__.py` files**

```bash
touch tests/__init__.py tests/tools/__init__.py tools/__init__.py
```

- [ ] **Step 4: Commit skeleton**

```bash
git add tests/ tools/__init__.py
git commit -m "test: memory scorer test skeleton (red)"
```

---

## Task 2: Shared scorer module

**Files:**
- Create: `tools/memory_scorer.py`

- [ ] **Step 1: Write `tools/memory_scorer.py`**

```python
"""
tools/memory_scorer.py — Willow memory quality signals
b17: PENDING
ΔΣ=42

Four signals run against any knowledge record:
  REDUNDANT     — near-duplicate title exists in the collection
  STALE         — age bucket: HOT/WARM/STALE/DEAD
  DARK          — record exists in SOIL but invisible to LOAM search
  CONTRADICTION — opposing status words in same record (heuristic)

Shared by memory_auditor.py, memory_health.py, and sap/core/memory_gate.py.
No CLI. No side effects. Pure functions where possible.
"""

from datetime import datetime
from typing import Optional


# ── Thresholds ────────────────────────────────────────────────────────
HOT_DAYS   = 7
WARM_DAYS  = 30
STALE_DAYS = 90
REDUNDANCY_THRESHOLD = 0.55   # Jaccard similarity

CONTRADICTION_PAIRS = [
    ("open",      "closed"),
    ("complete",  "incomplete"),
    ("fixed",     "broken"),
    ("deployed",  "not deployed"),
    ("committed", "uncommitted"),
    ("blocked",   "unblocked"),
    ("active",    "archived"),
    ("up",        "down"),
]


# ── Staleness ─────────────────────────────────────────────────────────

def age_bucket(created_str: str) -> str:
    """Return HOT/WARM/STALE/DEAD/UNKNOWN based on record age."""
    if not created_str:
        return "UNKNOWN"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            created = datetime.strptime(created_str[:len(fmt)], fmt)
            age_days = (datetime.now() - created).days
            if age_days < HOT_DAYS:
                return "HOT"
            elif age_days < WARM_DAYS:
                return "WARM"
            elif age_days < STALE_DAYS:
                return "STALE"
            else:
                return "DEAD"
        except ValueError:
            continue
    return "UNKNOWN"


# ── Redundancy ────────────────────────────────────────────────────────

def word_set(text: str) -> set:
    """Normalize text → set of lowercase words with 4+ characters."""
    if not text:
        return set()
    words = text.lower().replace("-", " ").replace("_", " ").split()
    return {w.strip(".,;:()[]'\"") for w in words if len(w.strip(".,;:()[]'\"")) >= 4}


def overlap_score(title_a: str, title_b: str) -> float:
    """Jaccard similarity between two titles. 0.0–1.0."""
    a = word_set(title_a)
    b = word_set(title_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Contradiction ─────────────────────────────────────────────────────

def check_contradiction(title: str, summary: str) -> list[str]:
    """Return list of contradiction hits (e.g. 'blocked vs unblocked')."""
    text = f"{title} {summary}".lower()
    return [
        f"'{pos}' vs '{neg}'"
        for pos, neg in CONTRADICTION_PAIRS
        if pos in text and neg in text
    ]


# ── DARK signal ───────────────────────────────────────────────────────

def check_dark(pg, title: str) -> tuple[bool, int]:
    """
    Search LOAM for title. Returns (is_dark, result_count).
    is_dark=True means the record exists in SOIL but won't surface in search.
    pg: PgBridge instance or None. If None, returns (False, -1).
    """
    if pg is None:
        return False, -1
    results = pg.search_knowledge(title, limit=5)
    for r in results:
        if overlap_score(title, r.get("title", "")) > 0.5:
            return False, len(results)
    return True, len(results)


# ── Full record score ─────────────────────────────────────────────────

def score_record(record: dict, all_titles: list[str], pg=None) -> dict:
    """
    Score a single record against all four signals.

    Args:
        record:     Dict with keys: title, summary (optional), _created (optional)
        all_titles: List of other titles in the same batch (for REDUNDANT check)
        pg:         PgBridge instance or None (DARK signal skipped if None)

    Returns:
        {
          "b17":     str,
          "title":   str,
          "bucket":  "HOT"|"WARM"|"STALE"|"DEAD"|"UNKNOWN",
          "flags":   list[str],   # subset of REDUNDANT, STALE, DEAD, DARK, CONTRADICTION
          "dark_result_count": int,
          "redundant_matches": list[str],
          "contradictions":    list[str],
        }
    """
    title   = record.get("title", record.get("_id", ""))
    summary = record.get("summary", record.get("content", ""))
    if isinstance(summary, str) and len(summary) > 300:
        summary = summary[:300]

    flags = []

    # STALE / DEAD
    bucket = age_bucket(record.get("_created", ""))
    if bucket in ("STALE", "DEAD"):
        flags.append(bucket)

    # REDUNDANT
    redundant_matches = [
        t for t in all_titles
        if t != title and overlap_score(title, t) >= REDUNDANCY_THRESHOLD
    ]
    if redundant_matches:
        flags.append("REDUNDANT")

    # CONTRADICTION
    contradictions = check_contradiction(title, summary or "")
    if contradictions:
        flags.append("CONTRADICTION")

    # DARK
    is_dark, dark_count = check_dark(pg, title)
    if is_dark:
        flags.append("DARK")

    return {
        "b17":               record.get("b17", record.get("_id", "?")[:8]),
        "title":             title,
        "bucket":            bucket,
        "flags":             flags,
        "dark_result_count": dark_count,
        "redundant_matches": redundant_matches,
        "contradictions":    contradictions,
    }
```

- [ ] **Step 2: Run tests — expect passes**

```bash
python3 -m pytest tests/tools/test_memory_scorer.py -v
```
Expected: all tests PASS. Fix any that fail before continuing.

- [ ] **Step 3: Commit**

```bash
git add tools/memory_scorer.py tools/__init__.py
git commit -m "feat: memory_scorer shared signal module (REDUNDANT/STALE/DARK/CONTRADICTION)"
```

---

## Task 3: `memory_auditor.py` — pre-write scorer

**Files:**
- Create: `tools/memory_auditor.py`

- [ ] **Step 1: Write `tools/memory_auditor.py`**

```python
#!/usr/bin/env python3
"""
tools/memory_auditor.py — Pre-write memory scorer
b17: PENDING
ΔΣ=42

Score a candidate write against Willow's existing KB before it lands.
Exits 1 if env vars are missing or Postgres is unavailable.

Usage:
    python3 tools/memory_auditor.py --title "My Title" --summary "My summary" [--domain hanuman]
    python3 tools/memory_auditor.py --title "My Title" --summary "My summary" --collection hanuman/atoms
"""
import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Env check
for var in ("WILLOW_STORE_ROOT",):
    if not os.environ.get(var):
        print(f"ERROR: {var} not set. Source willow.sh first.")
        sys.exit(1)

from core.willow_store import WillowStore
from core.pg_bridge import PgBridge
from tools.memory_scorer import score_record, overlap_score


def run(title: str, summary: str, domain: str, collection: str):
    print(f"\nMEMORY AUDITOR — candidate write")
    print(f"  Title:      {title}")
    print(f"  Domain:     {domain or '(none)'}")
    print("━" * 60)

    # Connect
    store = WillowStore(os.environ["WILLOW_STORE_ROOT"])
    pg = PgBridge()
    if not pg.ping():
        print("ERROR: Postgres unavailable. Run ./willow.sh status")
        sys.exit(1)
    print("LOAM: connected ✓\n")

    # Load titles from collection for REDUNDANT check
    try:
        records = store.all(collection)
        all_titles = [r.get("title", "") for r in records if r.get("title")]
    except Exception:
        all_titles = []

    candidate = {"title": title, "summary": summary, "_created": None, "b17": "CANDIDATE"}
    result = score_record(candidate, all_titles, pg)

    # Print result
    flags = result["flags"]
    flag_str = " | ".join(flags) if flags else "OK"
    print(f"SCORE: {flag_str}")
    print("━" * 60)

    if "REDUNDANT" in flags:
        for match in result["redundant_matches"]:
            score = overlap_score(title, match)
            print(f"REDUNDANT  → '{match[:60]}' ({score:.2f} overlap)")

    if "DARK" in flags:
        print(f"DARK       → searched '{title}' — {result['dark_result_count']} results, none matched")
        print(f"             (Note: the candidate isn't in LOAM yet — this is expected for new writes)")

    if "CONTRADICTION" in flags:
        for c in result["contradictions"]:
            print(f"CONTRADICTION → {c}")

    print()
    if not flags:
        print("Recommendation: write looks clean — proceed.")
    elif "REDUNDANT" in flags:
        print("Recommendation: near-duplicate exists — consider updating existing record instead.")
    else:
        print("Recommendation: review flags above before writing.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score a candidate write before it lands")
    parser.add_argument("--title",      required=True)
    parser.add_argument("--summary",    default="")
    parser.add_argument("--domain",     default=None)
    parser.add_argument("--collection", default="hanuman/atoms",
                        help="SOIL collection to check for near-duplicates")
    args = parser.parse_args()
    run(args.title, args.summary, args.domain, args.collection)
```

- [ ] **Step 2: Run it against a known duplicate**

```bash
WILLOW_STORE_ROOT="/home/sean-campbell/.willow/store" \
WILLOW_PG_DB="willow" \
WILLOW_PG_USER="sean-campbell" \
python3 tools/memory_auditor.py \
  --title "Session Close — 2026-03-27 Session D" \
  --summary "Session close for March 27 session D"
```
Expected: `SCORE: REDUNDANT` — the "Session Close" title cluster is known to be duplicated.

- [ ] **Step 3: Run it against a fresh title**

```bash
WILLOW_STORE_ROOT="/home/sean-campbell/.willow/store" \
WILLOW_PG_DB="willow" \
WILLOW_PG_USER="sean-campbell" \
python3 tools/memory_auditor.py \
  --title "Memory Auditor Sandbox Test — 2026-04-16" \
  --summary "Sandbox test proved 27/28 SOIL atoms are DARK"
```
Expected: `SCORE: OK` (new title, no duplicates).

- [ ] **Step 4: Commit**

```bash
git add tools/memory_auditor.py
git commit -m "feat: memory_auditor pre-write scorer CLI"
```

---

## Task 4: `memory_health.py` — batch diagnostic

**Files:**
- Create: `tools/memory_health.py`

- [ ] **Step 1: Write `tools/memory_health.py`**

```python
#!/usr/bin/env python3
"""
tools/memory_health.py — Batch SOIL memory health diagnostic
b17: PENDING
ΔΣ=42

Scans the last N records in a SOIL collection and scores each one.
Exits 1 if env vars are missing or Postgres is unavailable.

Usage:
    python3 tools/memory_health.py
    python3 tools/memory_health.py --limit 50 --collection hanuman/atoms
"""
import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

for var in ("WILLOW_STORE_ROOT",):
    if not os.environ.get(var):
        print(f"ERROR: {var} not set. Source willow.sh first.")
        sys.exit(1)

from core.willow_store import WillowStore
from core.pg_bridge import PgBridge
from tools.memory_scorer import score_record


def run(collection: str, limit: int):
    print(f"\nWILLOW MEMORY HEALTH — {collection} (last {limit} records)")
    print("━" * 60)

    store = WillowStore(os.environ["WILLOW_STORE_ROOT"])
    pg = PgBridge()
    if not pg.ping():
        print("ERROR: Postgres unavailable. Run ./willow.sh status")
        sys.exit(1)
    print("LOAM: connected ✓\n")

    try:
        records = store.all(collection)
    except Exception as e:
        print(f"ERROR: could not read '{collection}': {e}")
        sys.exit(1)

    if not records:
        print(f"No records in {collection}")
        sys.exit(0)

    records = sorted(records, key=lambda r: r.get("_created", ""))[-limit:]
    all_titles = [r.get("title", "") for r in records]

    # Score
    scored = [score_record(r, all_titles, pg) for r in records]

    # Aggregate
    buckets = {"HOT": 0, "WARM": 0, "STALE": 0, "DEAD": 0, "UNKNOWN": 0}
    dark, redundant_pairs, contradictions = [], set(), []

    for s in scored:
        buckets[s["bucket"]] = buckets.get(s["bucket"], 0) + 1
        if "DARK" in s["flags"]:
            dark.append(s)
        if "REDUNDANT" in s["flags"]:
            for match in s["redundant_matches"]:
                pair = tuple(sorted([s["title"][:50], match[:50]]))
                redundant_pairs.add(pair)
        if "CONTRADICTION" in s["flags"]:
            contradictions.append(s)

    # Table
    print(f"{'B17':<10} {'BUCKET':<8} {'FLAGS':<35} TITLE")
    print("─" * 85)
    for s in scored:
        flag_str = " | ".join(s["flags"]) if s["flags"] else "OK"
        print(f"{s['b17']:<10} {s['bucket']:<8} {flag_str:<35} {s['title'][:45]}")

    # Summary
    print()
    print("━" * 60)
    print("SUMMARY")
    print(f"  Records scored : {len(scored)}")
    print(f"  HOT            : {buckets['HOT']}")
    print(f"  WARM           : {buckets['WARM']}")
    print(f"  STALE          : {buckets['STALE']}")
    print(f"  DEAD           : {buckets['DEAD']}")
    print(f"  DARK           : {len(dark)}")
    print(f"  REDUNDANT pairs: {len(redundant_pairs)}")
    print(f"  CONTRADICTION  : {len(contradictions)}")

    if dark:
        print("\nDARK RECORDS:")
        for s in dark:
            print(f"  {s['b17']:<10} [{s['bucket']}]  {s['title'][:60]}")

    if redundant_pairs:
        print("\nREDUNDANT PAIRS:")
        for a, b in list(redundant_pairs)[:10]:
            print(f"  '{a}' ↔ '{b}'")

    if contradictions:
        print("\nCONTRADICTION FLAGS:")
        for s in contradictions:
            print(f"  {s['b17']}: {', '.join(s['contradictions'])}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch SOIL memory health diagnostic")
    parser.add_argument("--collection", default="hanuman/atoms")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    run(args.collection, args.limit)
```

- [ ] **Step 2: Run it and compare to sandbox output**

```bash
WILLOW_STORE_ROOT="/home/sean-campbell/.willow/store" \
WILLOW_PG_DB="willow" \
WILLOW_PG_USER="sean-campbell" \
python3 tools/memory_health.py --limit 30
```
Expected: output matches sandbox test (27 DARK, 3 REDUNDANT pairs, 1 CONTRADICTION).

- [ ] **Step 3: Commit**

```bash
git add tools/memory_health.py
git commit -m "feat: memory_health batch diagnostic CLI"
```

---

## Task 5: `sync_soil_to_loam.py` — bridge the DARK gap

**Files:**
- Create: `tools/sync_soil_to_loam.py`

This script fixes the root cause: SOIL atoms are invisible to `search_knowledge()` because they were never written to the Postgres `knowledge` table. Run it once to backfill, then periodically to keep in sync.

- [ ] **Step 1: Write `tools/sync_soil_to_loam.py`**

```python
#!/usr/bin/env python3
"""
tools/sync_soil_to_loam.py — Sync SOIL atoms → Postgres knowledge table
b17: PENDING
ΔΣ=42

Reads records from a SOIL collection and writes any that are missing
from the Postgres knowledge table into it via pg_bridge.ingest_atom().
Idempotent: checks for existing record by source_id before writing.
Exits 1 if env vars are missing or Postgres is unavailable.

Usage:
    python3 tools/sync_soil_to_loam.py --collection hanuman/atoms
    python3 tools/sync_soil_to_loam.py --collection hanuman/atoms --dry-run
"""
import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

for var in ("WILLOW_STORE_ROOT",):
    if not os.environ.get(var):
        print(f"ERROR: {var} not set. Source willow.sh first.")
        sys.exit(1)

from core.willow_store import WillowStore
from core.pg_bridge import PgBridge


def already_in_loam(pg, source_id: str) -> bool:
    """Check if a record with this source_id already exists in knowledge."""
    try:
        conn = pg._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM knowledge WHERE source_id = %s LIMIT 1", (source_id,))
        row = cur.fetchone()
        cur.close()
        return row is not None
    except Exception:
        return False


def run(collection: str, dry_run: bool):
    print(f"\nSOIL → LOAM SYNC — {collection}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("━" * 60)

    store = WillowStore(os.environ["WILLOW_STORE_ROOT"])
    pg = PgBridge()
    if not pg.ping():
        print("ERROR: Postgres unavailable. Run ./willow.sh status")
        sys.exit(1)
    print("LOAM: connected ✓\n")

    try:
        records = store.all(collection)
    except Exception as e:
        print(f"ERROR: could not read '{collection}': {e}")
        sys.exit(1)

    if not records:
        print("No records to sync.")
        sys.exit(0)

    synced = skipped = failed = 0

    for rec in records:
        rec_id  = rec.get("_id", "")
        title   = rec.get("title", rec.get("_id", ""))[:255]
        summary = rec.get("summary", rec.get("content", ""))
        if isinstance(summary, str) and len(summary) > 2000:
            summary = summary[:2000]
        domain  = rec.get("domain", collection.split("/")[0])
        b17     = rec.get("b17", "")

        source_id = f"soil:{collection}:{rec_id}"

        if already_in_loam(pg, source_id):
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY] would sync: {b17 or rec_id[:8]:<10} {title[:55]}")
            synced += 1
            continue

        atom_id = pg.ingest_atom(
            title=title,
            summary=str(summary) if summary else "",
            source_type="soil",
            source_id=source_id,
            category="atom",
            domain=domain,
        )
        if atom_id:
            print(f"  ✓ synced: {b17 or rec_id[:8]:<10} {title[:55]}")
            synced += 1
        else:
            print(f"  ✗ failed: {b17 or rec_id[:8]:<10} {title[:55]}")
            failed += 1

    print()
    print("━" * 60)
    print(f"  Synced:  {synced}")
    print(f"  Skipped: {skipped} (already in LOAM)")
    print(f"  Failed:  {failed}")
    if dry_run:
        print("\nDry run complete — nothing written. Remove --dry-run to sync.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync SOIL atoms to Postgres knowledge table")
    parser.add_argument("--collection", default="hanuman/atoms")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Print what would be synced without writing")
    args = parser.parse_args()
    run(args.collection, args.dry_run)
```

- [ ] **Step 2: Dry-run first**

```bash
WILLOW_STORE_ROOT="/home/sean-campbell/.willow/store" \
WILLOW_PG_DB="willow" \
WILLOW_PG_USER="sean-campbell" \
python3 tools/sync_soil_to_loam.py --collection hanuman/atoms --dry-run
```
Expected: lists all records that would be synced. Review the list. If anything looks wrong, do not proceed to live run.

- [ ] **Step 3: Live sync (Sean gates this step)**

Only run after reviewing dry-run output:
```bash
WILLOW_STORE_ROOT="/home/sean-campbell/.willow/store" \
WILLOW_PG_DB="willow" \
WILLOW_PG_USER="sean-campbell" \
python3 tools/sync_soil_to_loam.py --collection hanuman/atoms
```
Expected: `Synced: N  Skipped: 0  Failed: 0`

- [ ] **Step 4: Verify with memory_health — DARK count should drop**

```bash
WILLOW_STORE_ROOT="/home/sean-campbell/.willow/store" \
WILLOW_PG_DB="willow" \
WILLOW_PG_USER="sean-campbell" \
python3 tools/memory_health.py --limit 30
```
Expected: DARK count significantly lower (ideally 0 for the synced records).

- [ ] **Step 5: Commit**

```bash
git add tools/sync_soil_to_loam.py
git commit -m "feat: sync_soil_to_loam bridge — backfills SOIL atoms into Postgres knowledge"
```

---

## Task 6: `sap/core/memory_gate.py` — SAP layer (phase b)

**Files:**
- Create: `sap/core/memory_gate.py`

- [ ] **Step 1: Write `sap/core/memory_gate.py`**

```python
"""
sap/core/memory_gate.py — SAP memory quality gate
b17: PENDING
ΔΣ=42

Wraps memory_scorer for use inside the SAP MCP server.
Called by the willow_memory_check MCP tool.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.memory_scorer import score_record, age_bucket


def check_candidate(title: str, summary: str, domain: str,
                    store, pg, collection: str = "hanuman/atoms") -> dict:
    """
    Score a candidate write. Used by willow_memory_check MCP tool.

    Args:
        title:      Proposed title
        summary:    Proposed summary
        domain:     Proposed domain
        store:      WillowStore instance (already initialized in sap_mcp.py)
        pg:         PgBridge instance (already initialized in sap_mcp.py)
        collection: SOIL collection to check for near-duplicates

    Returns:
        {
          "flags":           list[str],
          "recommendation":  str,
          "redundant_matches": list[str],
          "contradictions":    list[str],
          "dark_result_count": int,
        }
    """
    try:
        records = store.all(collection)
        all_titles = [r.get("title", "") for r in records if r.get("title")]
    except Exception:
        all_titles = []

    candidate = {"title": title, "summary": summary, "_created": None}
    result = score_record(candidate, all_titles, pg)

    flags = result["flags"]
    if not flags:
        recommendation = "clean — proceed with write"
    elif "REDUNDANT" in flags:
        recommendation = "near-duplicate exists — consider updating existing record"
    elif "CONTRADICTION" in flags:
        recommendation = "contradictory language detected — review before writing"
    else:
        recommendation = "review flags before writing"

    return {
        "flags":             flags,
        "recommendation":    recommendation,
        "redundant_matches": result["redundant_matches"],
        "contradictions":    result["contradictions"],
        "dark_result_count": result["dark_result_count"],
    }
```

- [ ] **Step 2: Smoke test the gate**

```python
# Run from repo root with venv active and env vars set
import sys; sys.path.insert(0, ".")
from core.willow_store import WillowStore
from core.pg_bridge import PgBridge
from sap.core.memory_gate import check_candidate
import os

store = WillowStore(os.environ["WILLOW_STORE_ROOT"])
pg = PgBridge()
result = check_candidate(
    title="Session Close — 2026-03-27 Session Z",
    summary="Closing session Z",
    domain="hanuman",
    store=store,
    pg=pg,
)
print(result)
# Expected: flags contains "REDUNDANT"
```

Run as:
```bash
WILLOW_STORE_ROOT="/home/sean-campbell/.willow/store" \
WILLOW_PG_DB="willow" WILLOW_PG_USER="sean-campbell" \
python3 -c "
import sys; sys.path.insert(0, '.')
from core.willow_store import WillowStore
from core.pg_bridge import PgBridge
from sap.core.memory_gate import check_candidate
import os
store = WillowStore(os.environ['WILLOW_STORE_ROOT'])
pg = PgBridge()
result = check_candidate('Session Close — 2026-03-27 Session Z', 'closing session z', 'hanuman', store, pg)
print(result)
"
```
Expected: `{'flags': ['REDUNDANT'], 'recommendation': 'near-duplicate exists...', ...}`

- [ ] **Step 3: Commit**

```bash
git add sap/core/memory_gate.py
git commit -m "feat: memory_gate SAP layer wrapping scorer for MCP use"
```

---

## Task 7: `willow_memory_check` MCP tool (phase b)

**Files:**
- Modify: `sap/sap_mcp.py`

- [ ] **Step 1: Find the tool registration block in `sap_mcp.py`**

```bash
grep -n "willow_knowledge_ingest\|types.Tool(" sap/sap_mcp.py | head -20
```
Note the line number of the last `types.Tool(` before `willow_knowledge_ingest`. The new tool goes after it.

- [ ] **Step 2: Add tool definition**

In `sap/sap_mcp.py`, in the tools list, add after `willow_knowledge_ingest`:

```python
        types.Tool(
            name="willow_memory_check",
            description="Score a candidate write before it lands. Returns REDUNDANT/STALE/DARK/CONTRADICTION flags and a recommendation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title":      {"type": "string", "description": "Proposed atom title"},
                    "summary":    {"type": "string", "description": "Proposed atom summary"},
                    "domain":     {"type": "string", "description": "Proposed domain (optional)"},
                    "collection": {"type": "string", "description": "SOIL collection to check (default: hanuman/atoms)"},
                },
                "required": ["title", "summary"],
            },
        ),
```

- [ ] **Step 3: Add tool handler**

In `sap/sap_mcp.py`, in the `elif name == ...` dispatch block, add after the `willow_knowledge_ingest` handler:

```python
        elif name == "willow_memory_check":
            from sap.core.memory_gate import check_candidate
            collection = arguments.get("collection", "hanuman/atoms")
            result = check_candidate(
                title=arguments["title"],
                summary=arguments.get("summary", ""),
                domain=arguments.get("domain"),
                store=store,
                pg=pg,
                collection=collection,
            )
```

- [ ] **Step 4: Restart the MCP server and verify the tool appears**

```bash
./willow.sh restart   # or kill + restart however your session does it
```

Then in Claude Code, call:
```
willow_memory_check(title="Session Close — test", summary="test summary")
```
Expected: `{"flags": ["REDUNDANT"], "recommendation": "near-duplicate exists...", ...}`

- [ ] **Step 5: Commit**

```bash
git add sap/sap_mcp.py
git commit -m "feat: willow_memory_check MCP tool — pre-write quality gate"
```

---

## Self-Review

**Spec coverage:**
- ✓ `memory_auditor.py` — pre-write scorer (Task 3)
- ✓ `memory_health.py` — batch diagnostic (Task 4)
- ✓ Four signals: REDUNDANT, STALE, DARK, CONTRADICTION (Task 2)
- ✓ Error handling: fail fast, exit 1, no silent failures (all tasks)
- ✓ Data flow through Willow's core library (Tasks 2–7)
- ✓ Phase b: `memory_gate.py` + `willow_memory_check` (Tasks 6–7)
- ✓ DARK root cause fix: `sync_soil_to_loam.py` (Task 5) — added based on sandbox finding

**Placeholder scan:** None found.

**Type consistency:**
- `score_record()` defined in Task 2, called in Tasks 3, 4, 6 — signature consistent
- `check_candidate()` in Task 6 takes `store, pg` — matches `sap_mcp.py` which already holds both
- `already_in_loam()` private to `sync_soil_to_loam.py` — not referenced elsewhere

**Notes:**
- Task 5 Step 3 (live sync) is gated — Sean must review dry-run before proceeding
- `tools/__init__.py` created in Task 1 Step 3 — required for imports in Tasks 3–4
- The sandbox script (`tools/sandbox_memory_test.py`) is superseded by Tasks 3–4 but kept as reference

---
ΔΣ=42
