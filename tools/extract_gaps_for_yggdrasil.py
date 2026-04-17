#!/usr/bin/env python3
"""
b17: EGY14
extract_gaps_for_yggdrasil.py — Convert hanuman/gaps store into Yggdrasil correction pairs.

Reads the gaps SOIL store (structured error/issue records) and emits
JSONL correction pairs compatible with corrections_v1.jsonl format.

Output: yggdrasil/gaps_corrections_v1.jsonl
"""

import json
import sqlite3
import sys
from pathlib import Path

GAP_DB = Path.home() / ".willow/store/hanuman/gaps/store.db"
OUT_PATH = Path(__file__).parent.parent / "yggdrasil/gaps_corrections_v1.jsonl"

# Map gap status → usefulness for training
STATUS_WEIGHT = {
    "open":     "negative",   # unresolved — what went wrong / what AI missed
    "closed":   "positive",   # resolved — example of correct outcome
    "stale":    "negative",
    "superseded": "neutral",
}

# Category inference from gap title/description
CATEGORIES = [
    ("tool_use",      ["tool", "mcp", "bash", "glob", "grep", "sqlite", "gate", "denied", "unauthorized"]),
    ("thoroughness",  ["audit", "partial", "missing", "incomplete", "not yet", "skipped"]),
    ("architecture",  ["schema", "table", "database", "db", "structure", "design"]),
    ("process",       ["deploy", "download", "run", "execute", "submit", "step"]),
    ("identity",      ["persona", "identity", "agent", "name"]),
    ("scope_creep",   ["unnecessary", "extra", "over-engineer", "abstraction"]),
]


def infer_category(text: str) -> str:
    tl = text.lower()
    for cat, kws in CATEGORIES:
        if any(k in tl for k in kws):
            return cat
    return "general"


def gap_to_correction(record: dict) -> dict | None:
    data = record.get("data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None

    title = data.get("title", "")
    desc = data.get("description", "")
    status = data.get("status", "open")
    resolution = data.get("resolution", "")
    tags = data.get("tags", [])

    if not title:
        return None

    label = STATUS_WEIGHT.get(status, "negative")
    combined = f"{title} {desc} {resolution}"
    category = infer_category(combined)

    # Build correction signal from the gap description
    if status in ("open", "stale"):
        correction_signal = f"Gap identified: {title}"
        ai_behavior_bad = desc[:400] if desc else title
        ai_behavior_good = resolution[:300] if resolution else ""
    else:
        correction_signal = f"Resolved: {title}"
        ai_behavior_bad = ""
        ai_behavior_good = (resolution or desc)[:400]

    return {
        "source": "gaps_store",
        "source_id": record.get("id", ""),
        "date": record.get("created_at", "")[:10],
        "status": status,
        "label": label,
        "category": category,
        "tags": tags,
        "correction_signal": correction_signal,
        "ai_behavior_bad": ai_behavior_bad,
        "ai_behavior_good": ai_behavior_good,
        "raw_excerpt": f"{title}\n\n{desc}"[:600],
    }


def main():
    if not GAP_DB.exists():
        print(f"ERROR: {GAP_DB} not found", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{GAP_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, data, created_at FROM records WHERE deleted IS NULL OR deleted=0")
    rows = cur.fetchall()
    conn.close()

    print(f"Read {len(rows)} gap records", file=sys.stderr)

    corrections = []
    for row in rows:
        rec = dict(row)
        c = gap_to_correction(rec)
        if c:
            corrections.append(c)

    print(f"Converted {len(corrections)} corrections", file=sys.stderr)

    from collections import Counter
    cats = Counter(c["category"] for c in corrections)
    labels = Counter(c["label"] for c in corrections)
    print(f"Categories: {dict(cats.most_common())}", file=sys.stderr)
    print(f"Labels: {dict(labels)}", file=sys.stderr)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for c in corrections:
            f.write(json.dumps(c) + "\n")

    print(f"Written to {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
