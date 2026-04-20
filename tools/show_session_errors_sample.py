#!/usr/bin/env python3
import json
from pathlib import Path

f = Path("yggdrasil/session_errors_v1.jsonl")
repeat_edits = []
bash_errors = []

for line in f.open():
    d = json.loads(line)
    if d.get("error_type") == "repeat_edit":
        repeat_edits.append(d)
    elif d.get("error_type") == "bash_error":
        bash_errors.append(d)

print(f"=== REPEAT EDITS ({len(repeat_edits)} total) — first 5 ===")
for d in repeat_edits[:5]:
    print(f"\n  signal: {d['correction_signal']}")
    print(f"  file:   {d['raw_excerpt']}")
    print(f"  source: {d['source_file']}")

print(f"\n=== BASH ERRORS ({len(bash_errors)} total) — first 5 ===")
for d in bash_errors[:5]:
    print(f"\n  signal: {d['correction_signal'][:120]}")
    print(f"  source: {d['source_file']}")
