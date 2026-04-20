#!/usr/bin/env python3
"""
b17: SCC83
sample_cube_cells.py — Sample cube_cells_organic to understand JSOL turn format.

Looks for records that contain error/bash/fix signals.
"""

import json
import sqlite3
from pathlib import Path

DB = Path.home() / ".willow/store/cube_cells_organic/store.db"


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # First: understand the data shape by sampling 5 records
    print("=== RANDOM SAMPLE (5 records) ===")
    cur.execute("SELECT id, data FROM records WHERE deleted IS NULL OR deleted=0 LIMIT 5")
    for row in cur.fetchall():
        try:
            d = json.loads(row["data"])
        except Exception:
            d = {"_raw": str(row["data"])[:300]}
        print(f"\nid: {row['id'][:20]}")
        print(f"  keys: {list(d.keys())[:15]}")
        for k in ("type", "role", "event", "tool", "status", "error", "content", "text"):
            if k in d:
                print(f"  {k}: {str(d[k])[:150]}")

    # Second: search for error/bash/fix patterns
    print("\n\n=== ERROR-SIGNAL SEARCH ===")
    error_terms = [
        ("bash_error",    "data LIKE '%\"stderr\"%' OR data LIKE '%error%bash%'"),
        ("tool_error",    "data LIKE '%tool_error%' OR data LIKE '%ToolError%'"),
        ("file_edit",     "data LIKE '%Edit%' OR data LIKE '%file_edit%'"),
        ("retry",         "data LIKE '%retry%' OR data LIKE '%again%'"),
        ("fix",           "data LIKE '%fix%' OR data LIKE '%fixed%'"),
    ]

    for label, clause in error_terms:
        cur.execute(f"SELECT COUNT(*) FROM records WHERE ({clause}) AND (deleted IS NULL OR deleted=0)")
        count = cur.fetchone()[0]
        print(f"  {label}: {count:,} matching records")

    # Third: sample bash errors
    print("\n\n=== BASH ERROR SAMPLES ===")
    cur.execute("""
        SELECT id, data FROM records
        WHERE (data LIKE '%stderr%' OR data LIKE '%exit_code%' OR data LIKE '%returncode%')
          AND (deleted IS NULL OR deleted=0)
        LIMIT 5
    """)
    for row in cur.fetchall():
        try:
            d = json.loads(row["data"])
        except Exception:
            continue
        print(f"\nid: {row['id'][:20]}")
        print(f"  keys: {list(d.keys())[:15]}")
        for k in ("type", "role", "tool", "stderr", "stdout", "exit_code", "returncode", "error", "content"):
            if k in d:
                print(f"  {k}: {str(d[k])[:200]}")

    conn.close()


if __name__ == "__main__":
    main()
