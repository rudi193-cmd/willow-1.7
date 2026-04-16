#!/usr/bin/env python3
"""
tools/sync_soil_to_loam.py — Sync SOIL atoms → Postgres knowledge table
b17: PENDING
ΔΣ=42

Reads records from a SOIL collection and writes any missing from the
Postgres knowledge table into it via pg_bridge.ingest_atom().
Idempotent: checks source_id before writing.
Exits 1 if env vars are missing or Postgres is unavailable.

Usage:
    python3 tools/sync_soil_to_loam.py --collection hanuman/atoms --dry-run
    python3 tools/sync_soil_to_loam.py --collection hanuman/atoms
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
