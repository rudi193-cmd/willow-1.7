#!/usr/bin/env python3
"""
sandbox_memory_test.py — Memory auditor proof of concept
b17: 44515
ΔΣ=42

Runs 4 signals against the last N records in a SOIL collection:
  REDUNDANT   — near-duplicate title exists in the collection
  STALE       — HOT/WARM/STALE/DEAD by age
  DARK        — record exists but doesn't surface in LOAM search
  CONTRADICTION — opposing status/conclusion on same subject (heuristic)

Usage:
  cd /home/sean-campbell/github/willow-1.7
  source .venv/bin/activate  (or whatever your venv is)
  python tools/sandbox_memory_test.py --limit 30
  python tools/sandbox_memory_test.py --limit 30 --collection hanuman/atoms
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── Env check ─────────────────────────────────────────────────────────
REQUIRED_ENV = ["WILLOW_STORE_ROOT"]
missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
if missing:
    print(f"ERROR: missing env vars: {', '.join(missing)}")
    print("Run: source willow.sh or set WILLOW_STORE_ROOT manually")
    sys.exit(1)

from core.willow_store import WillowStore
from core.pg_bridge import PgBridge

# ── Config ────────────────────────────────────────────────────────────
STALE_THRESHOLDS = {
    "HOT":   7,
    "WARM":  30,
    "STALE": 90,
    "DEAD":  9999,
}

CONTRADICTION_PAIRS = [
    ("open", "closed"),
    ("complete", "incomplete"),
    ("fixed", "broken"),
    ("up", "down"),
    ("deployed", "not deployed"),
    ("committed", "uncommitted"),
    ("blocked", "unblocked"),
    ("active", "archived"),
]

# Word overlap threshold for REDUNDANT flag (0.0–1.0)
REDUNDANCY_THRESHOLD = 0.55


# ── Helpers ───────────────────────────────────────────────────────────

def age_bucket(created_str: str) -> str:
    """Return HOT/WARM/STALE/DEAD based on record age."""
    try:
        # Handle various date formats
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                created = datetime.strptime(created_str[:19], fmt[:len(created_str[:19])])
                break
            except ValueError:
                continue
        else:
            return "UNKNOWN"
        age_days = (datetime.now() - created).days
        if age_days < STALE_THRESHOLDS["HOT"]:
            return "HOT"
        elif age_days < STALE_THRESHOLDS["WARM"]:
            return "WARM"
        elif age_days < STALE_THRESHOLDS["STALE"]:
            return "STALE"
        else:
            return "DEAD"
    except Exception:
        return "UNKNOWN"


def word_set(text: str) -> set:
    """Normalize text to a set of lowercase words (4+ chars)."""
    if not text:
        return set()
    words = text.lower().replace("-", " ").replace("_", " ").split()
    return {w.strip(".,;:()[]") for w in words if len(w) >= 4}


def overlap_score(title_a: str, title_b: str) -> float:
    """Jaccard similarity between two titles."""
    a = word_set(title_a)
    b = word_set(title_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def check_contradiction(title: str, summary: str) -> list[str]:
    """Heuristic: flag if title or summary contains both sides of a known pair."""
    text = f"{title} {summary}".lower()
    hits = []
    for pos, neg in CONTRADICTION_PAIRS:
        if pos in text and neg in text:
            hits.append(f"'{pos}' vs '{neg}'")
    return hits


def check_dark(pg: PgBridge, title: str) -> tuple[bool, int]:
    """
    Search LOAM for the title. Return (is_dark, result_count).
    is_dark = True if title exists in store but doesn't surface in KB search.
    """
    if not pg:
        return False, -1
    results = pg.search_knowledge(title, limit=5)
    # Check if any result title overlaps significantly with ours
    for r in results:
        if overlap_score(title, r.get("title", "")) > 0.5:
            return False, len(results)
    return True, len(results)


# ── Main ──────────────────────────────────────────────────────────────

def run(collection: str, limit: int):
    print(f"\nWILLOW MEMORY SANDBOX TEST — {collection} (last {limit} records)")
    print("━" * 60)

    # Init store
    store_root = os.environ["WILLOW_STORE_ROOT"]
    store = WillowStore(store_root)

    # Init Postgres (optional)
    pg = None
    try:
        pg = PgBridge()
        if pg.ping():
            print("LOAM: connected ✓")
        else:
            print("LOAM: unavailable — DARK signal will be skipped")
            pg = None
    except Exception as e:
        print(f"LOAM: unavailable ({e}) — DARK signal will be skipped")

    print()

    # Load records
    try:
        records = store.all(collection)
    except Exception as e:
        print(f"ERROR: could not read collection '{collection}': {e}")
        sys.exit(1)

    if not records:
        print(f"No records found in {collection}")
        sys.exit(0)

    # Take last N by _created
    records = sorted(records, key=lambda r: r.get("_created", ""))[-limit:]

    # ── Score each record ─────────────────────────────────────────────
    results = []
    buckets = {"HOT": 0, "WARM": 0, "STALE": 0, "DEAD": 0, "UNKNOWN": 0}
    dark_list = []
    redundancy_pairs = []
    contradiction_list = []

    titles = [(r.get("title", r.get("_id", "")), r) for r in records]

    for i, (title, rec) in enumerate(titles):
        flags = []
        summary = rec.get("summary", rec.get("content", ""))
        if isinstance(summary, str) and len(summary) > 200:
            summary = summary[:200]

        # STALE signal
        bucket = age_bucket(rec.get("_created", ""))
        buckets[bucket] = buckets.get(bucket, 0) + 1
        if bucket in ("STALE", "DEAD"):
            flags.append(bucket)

        # REDUNDANT signal — compare against all other titles in batch
        for j, (other_title, _) in enumerate(titles):
            if i == j:
                continue
            score = overlap_score(title, other_title)
            if score >= REDUNDANCY_THRESHOLD:
                pair = tuple(sorted([title[:50], other_title[:50]]))
                if pair not in [p[0] for p in redundancy_pairs]:
                    redundancy_pairs.append((pair, score))
                if "REDUNDANT" not in flags:
                    flags.append("REDUNDANT")

        # CONTRADICTION signal (heuristic)
        contradictions = check_contradiction(title, summary or "")
        if contradictions:
            contradiction_list.append((title, contradictions))
            flags.append("CONTRADICTION")

        # DARK signal
        if pg:
            is_dark, result_count = check_dark(pg, title)
            if is_dark:
                dark_list.append((rec.get("b17", rec.get("_id", "?")), title, bucket))
                flags.append("DARK")

        results.append({
            "b17": rec.get("b17", rec.get("_id", "?")[:8]),
            "title": title[:55],
            "bucket": bucket,
            "flags": flags,
        })

    # ── Print results ─────────────────────────────────────────────────
    print(f"{'B17':<10} {'BUCKET':<8} {'FLAGS':<30} TITLE")
    print("─" * 80)
    for r in results:
        flag_str = " | ".join(r["flags"]) if r["flags"] else "OK"
        print(f"{r['b17']:<10} {r['bucket']:<8} {flag_str:<30} {r['title']}")

    print()
    print("━" * 60)
    print("SUMMARY")
    print(f"  Records scored : {len(results)}")
    print(f"  HOT            : {buckets['HOT']}")
    print(f"  WARM           : {buckets['WARM']}")
    print(f"  STALE          : {buckets['STALE']}")
    print(f"  DEAD           : {buckets['DEAD']}")
    print(f"  DARK           : {len(dark_list)}" + (" (LOAM unavailable)" if not pg else ""))
    print(f"  REDUNDANT pairs: {len(redundancy_pairs)}")
    print(f"  CONTRADICTION  : {len(contradiction_list)}")

    if dark_list:
        print()
        print("DARK RECORDS (exist in store, invisible to LOAM search):")
        for b17, title, bucket in dark_list:
            print(f"  {b17:<10} [{bucket}]  {title[:60]}")

    if redundancy_pairs:
        print()
        print("REDUNDANT PAIRS:")
        for (a, b), score in redundancy_pairs[:10]:
            print(f"  {score:.2f}  '{a}' ↔ '{b}'")

    if contradiction_list:
        print()
        print("CONTRADICTION FLAGS:")
        for title, hits in contradiction_list:
            print(f"  '{title[:55]}': {', '.join(hits)}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Willow memory sandbox test")
    parser.add_argument("--collection", default="hanuman/atoms",
                        help="SOIL collection to audit (default: hanuman/atoms)")
    parser.add_argument("--limit", type=int, default=30,
                        help="Number of most recent records to score (default: 30)")
    args = parser.parse_args()
    run(args.collection, args.limit)
