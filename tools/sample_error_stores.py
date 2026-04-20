#!/usr/bin/env python3
"""
b17: SES72
sample_error_stores.py — Sample content from error-signal SOIL stores.

Reads gaps, feedback, infractions, kart, shiva, and session stores
to find raw AI error data suitable for Yggdrasil training.
"""

import json
import sqlite3
from pathlib import Path

HOME = Path.home()
WILLOW_STORE = HOME / ".willow/store"

TARGETS = [
    ("gaps",        WILLOW_STORE / "hanuman/gaps/store.db"),
    ("feedback",    WILLOW_STORE / "hanuman/feedback/store.db"),
    ("infractions", WILLOW_STORE / "hanuman/infractions/store.db"),
    ("kart",        WILLOW_STORE / "hanuman/kart/store.db"),
    ("shiva",       WILLOW_STORE / "hanuman/shiva/store.db"),
    ("corrections", WILLOW_STORE / "hanuman/corrections/store.db"),
    ("session_work",WILLOW_STORE / "session/work/store.db"),
    ("session_meta",WILLOW_STORE / "session/meta/store.db"),
]

# Also look for raw_jsonls in the willow-1.7 repo
WILLOW_REPO = HOME / "github/willow-1.7"


def read_store(label, path, limit=5):
    if not path.exists():
        print(f"\n[{label}] NOT FOUND: {path}")
        return

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM records WHERE (deleted IS NULL OR deleted = 0)")
    count = cur.fetchone()[0]
    print(f"\n{'='*60}")
    print(f"[{label}] {path.name} — {count} active records")

    cur.execute("""
        SELECT id, data FROM records
        WHERE deleted IS NULL OR deleted = 0
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()

    for row in rows:
        try:
            d = json.loads(row["data"])
        except Exception:
            d = {"_raw": str(row["data"])[:300]}

        print(f"\n  id: {row['id'][:40]}")
        # Print key fields
        for key in ("type", "category", "event", "status", "error", "summary",
                    "title", "body", "content", "description", "text",
                    "correction_signal", "ai_behavior_bad", "ai_behavior_good"):
            if key in d:
                val = str(d[key])[:200]
                print(f"  {key}: {val}")

    conn.close()


def check_for_raw_jsonls():
    """Look for any DB with a raw_jsonls table."""
    print(f"\n{'='*60}")
    print("Searching for raw_jsonls tables...")
    for db_path in WILLOW_REPO.rglob("*.db"):
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE name='raw_jsonls'")
            if cur.fetchone():
                cur.execute("SELECT COUNT(*) FROM raw_jsonls")
                count = cur.fetchone()[0]
                print(f"  FOUND raw_jsonls in {db_path} — {count} rows")
                cur.execute("PRAGMA table_info(raw_jsonls)")
                cols = cur.fetchall()
                print(f"  cols: {[c[1] for c in cols]}")
                cur.execute("SELECT * FROM raw_jsonls LIMIT 2")
                for r in cur.fetchall():
                    print(f"  sample: {str(dict(r))[:200]}")
            conn.close()
        except Exception:
            pass


def main():
    for label, path in TARGETS:
        read_store(label, path)

    check_for_raw_jsonls()
    print(f"\n{'='*60}")
    print("Done.")


if __name__ == "__main__":
    main()
