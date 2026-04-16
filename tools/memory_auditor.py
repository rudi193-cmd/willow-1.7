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

    store = WillowStore(os.environ["WILLOW_STORE_ROOT"])
    pg = PgBridge()
    if not pg.ping():
        print("ERROR: Postgres unavailable. Run ./willow.sh status")
        sys.exit(1)
    print("LOAM: connected ✓\n")

    try:
        records = store.all(collection)
        all_titles = [r.get("title", "") for r in records if r.get("title")]
    except Exception:
        all_titles = []

    candidate = {"title": title, "summary": summary, "_created": None, "b17": "CANDIDATE"}
    result = score_record(candidate, all_titles, pg)

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
        print(f"             (Note: candidate not in LOAM yet — expected for new writes)")

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
    parser.add_argument("--collection", default="hanuman/atoms")
    args = parser.parse_args()
    run(args.title, args.summary, args.domain, args.collection)
