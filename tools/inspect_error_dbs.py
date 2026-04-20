#!/usr/bin/env python3
"""
b17: IED91
inspect_error_dbs.py — Inspect SQLite schemas in candidate error databases.

Run: python3 tools/inspect_error_dbs.py
"""

import sqlite3
import sys
from pathlib import Path

HOME = Path.home()

CANDIDATE_DBS = [
    HOME / "Ashokoa/agents/heimdallr/index/haumana_handoffs/handoffs.db",
    HOME / "Ashokoa/agents/hanuman/index/haumana_handoffs/handoffs.db",
    HOME / "github/willow-1.7/kart/kart_tasks.db",
    HOME / "github/willow-1.7/sap/log/gaps.jsonl",  # not sqlite, skip
    HOME / ".willow/shiva_sessions.db",
    HOME / ".willow/shiva.db",
    HOME / ".willow/fleet_feedback.db",
    HOME / ".willow/loam.db",
    HOME / "CUsersSean.claudecontext_store.db",
    HOME / "Ashokoa/agents/heimdallr/index/haumana_handoffs/handoffs.db",
]

# Also scan for any .db files in key dirs
SCAN_DIRS = [
    HOME / "github/willow-1.7",
    HOME / ".willow",
    HOME / "Ashokoa/agents",
]


def get_all_dbs():
    found = set()
    for d in SCAN_DIRS:
        if d.exists():
            for p in d.rglob("*.db"):
                found.add(p)
    for p in CANDIDATE_DBS:
        if p.suffix == ".db" and p.exists():
            found.add(p)
    return sorted(found)


def inspect_db(path: Path):
    print(f"\n{'='*60}")
    print(f"DB: {path}")
    print(f"Size: {path.stat().st_size:,} bytes")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name")
        objects = cur.fetchall()
        if not objects:
            print("  (empty — no tables)")
            conn.close()
            return

        for obj_name, obj_type in objects:
            print(f"\n  [{obj_type}] {obj_name}")
            try:
                cur.execute(f"PRAGMA table_info({obj_name})")
                cols = cur.fetchall()
                for col in cols:
                    cid, name, typ, notnull, dflt, pk = col
                    flags = []
                    if pk: flags.append("PK")
                    if notnull: flags.append("NOT NULL")
                    flag_str = f" ({', '.join(flags)})" if flags else ""
                    print(f"    {name}: {typ}{flag_str}")

                cur.execute(f"SELECT COUNT(*) FROM {obj_name}")
                count = cur.fetchone()[0]
                print(f"    → {count:,} rows")

                # Sample interesting columns for error/task databases
                error_cols = [c[1] for c in cols if any(k in c[1].lower() for k in
                    ("error", "stderr", "stdout", "exception", "traceback", "fail", "status", "result", "output", "bash", "cmd", "command"))]
                if error_cols and count > 0:
                    sample_col = error_cols[0]
                    try:
                        cur.execute(f"SELECT {sample_col} FROM {obj_name} WHERE {sample_col} IS NOT NULL AND {sample_col} != '' LIMIT 2")
                        samples = cur.fetchall()
                        for s in samples:
                            val = str(s[0])[:200]
                            print(f"    sample {sample_col}: {val!r}")
                    except Exception as e:
                        print(f"    (sample failed: {e})")

            except Exception as e:
                print(f"    (schema read failed: {e})")

        conn.close()
    except Exception as e:
        print(f"  ERROR: {e}")


def main():
    dbs = get_all_dbs()
    print(f"Found {len(dbs)} SQLite databases\n")
    for db in dbs:
        inspect_db(db)
    print(f"\n{'='*60}")
    print("Done.")


if __name__ == "__main__":
    main()
