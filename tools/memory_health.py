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

    scored = [score_record(r, all_titles, pg) for r in records]

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

    print(f"{'B17':<10} {'BUCKET':<8} {'FLAGS':<35} TITLE")
    print("─" * 85)
    for s in scored:
        flag_str = " | ".join(s["flags"]) if s["flags"] else "OK"
        print(f"{s['b17']:<10} {s['bucket']:<8} {flag_str:<35} {s['title'][:45]}")

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
