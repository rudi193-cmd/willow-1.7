#!/usr/bin/env python3
# b17: CSF V9
"""
combine_sft.py — Merge SFT files, deduplicate, PII-check, write sft_v9.jsonl
"""
import json, re, sys
from pathlib import Path

REPO = Path(__file__).parent.parent
SOURCES = [
    REPO / "yggdrasil" / "sft_core_v1.jsonl",        # 50 hand-crafted core pairs
    REPO / "yggdrasil" / "sft_distilled_v1.jsonl",    # 531 KB atoms, M2.7 voice-coached
    REPO / "yggdrasil" / "sft_kart_v1.jsonl",         # 904 Kart execution pairs
    REPO / "yggdrasil" / "sft_repo_v1.jsonl",         # 248 repo files — identity/arch/gate/kart
]
OUT = REPO / "yggdrasil" / "sft_v9.jsonl"

PII = [
    re.compile(r'\bWC \d{2}-\d+\b'),
    re.compile(r'\b\d{2}-\d{5}-j\d+\b'),
    re.compile(r'System-Induced Pathology'),
    re.compile(r'L5-L6'),
    re.compile(r'/home/[a-zA-Z0-9_-]+/'),
]

seen, written, skipped_pii, skipped_dup = set(), 0, 0, 0

with OUT.open("w") as out:
    for src in SOURCES:
        for line in src.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            key = rec.get("instruction", "").strip().lower()[:80]
            if key in seen:
                skipped_dup += 1
                continue
            seen.add(key)

            combined = rec.get("instruction", "") + " " + rec.get("response", "")
            if any(p.search(combined) for p in PII):
                skipped_pii += 1
                print(f"  PII flagged: {rec.get('instruction','')[:60]}")
                continue

            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1

print(f"Written:      {written}")
print(f"Skipped dup:  {skipped_dup}")
print(f"Skipped PII:  {skipped_pii}")
print(f"Output:       {OUT}")
