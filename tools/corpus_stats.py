#!/usr/bin/env python3
"""Quick stats on the Yggdrasil training corpus."""
import json
from collections import Counter
from pathlib import Path

# Prefer v2 if it exists, fall back to v1
def best_file(stem):
    v2 = Path(f"yggdrasil/{stem}_v2.jsonl")
    v1 = Path(f"yggdrasil/{stem}_v1.jsonl")
    return v2 if v2.exists() else v1

FILES = [
    best_file("corrections"),
    best_file("gaps_corrections"),
    best_file("session_errors"),
]

total = 0
has_pair = 0  # DPO-ready: has a "bad" signal AND "good" response
has_bad_only = 0
has_good_only = 0
labels = Counter()
categories = Counter()
error_types = Counter()

for p in FILES:
    if not p.exists():
        continue
    count = 0
    file_pairs = 0
    for line in p.open():
        d = json.loads(line)
        count += 1
        total += 1
        # "bad" = ai_behavior_bad OR correction_signal (corrections records use the latter)
        bad = (d.get("ai_behavior_bad") or d.get("correction_signal") or "").strip()
        good = d.get("ai_behavior_good", "").strip()
        labels[d.get("label", "?")] += 1
        categories[d.get("category", "?")] += 1
        if d.get("error_type"):
            error_types[d["error_type"]] += 1
        if bad and good:
            has_pair += 1
            file_pairs += 1
        elif bad:
            has_bad_only += 1
        elif good:
            has_good_only += 1
    print(f"  {p}: {count} records, {file_pairs} complete pairs")

print(f"\nTotal records:     {total}")
print(f"Complete pairs:    {has_pair}  (bad + good both present — DPO-ready)")
print(f"Bad-only:          {has_bad_only}  (negative examples, need good counterpart)")
print(f"Good-only:         {has_good_only}")
print(f"\nLabels:     {dict(labels.most_common())}")
print(f"Categories: {dict(categories.most_common())}")
if error_types:
    print(f"Error types:{dict(error_types.most_common())}")
print(f"\nDPO readiness: {has_pair/total*100:.0f}% of records are complete pairs")
