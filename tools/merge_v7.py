#!/usr/bin/env python3
"""
merge_v7.py — Merge and deduplicate all Yggdrasil v7 DPO pairs.

Reads:
  yggdrasil/dpo_pairs_v7_regen.jsonl   (regenerated existing pairs)
  yggdrasil/dpo_pairs_v7_new.jsonl     (new refusal/governance/BTR pairs)

Writes:
  yggdrasil-training-data/dpo_pairs_v7.jsonl  (final merged dataset for Kaggle)

Usage:
  python3 tools/merge_v7.py
  python3 tools/merge_v7.py --keep-meta   # preserve _source/_error_type fields

b17: V7MG1
ΔΣ=42
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

WILLOW_ROOT = Path(__file__).parent.parent.resolve()

REGEN_FILE = WILLOW_ROOT / "yggdrasil" / "dpo_pairs_v7_regen.jsonl"
NEW_FILE   = WILLOW_ROOT / "yggdrasil" / "dpo_pairs_v7_new.jsonl"
OUTPUT     = Path("/home/sean-campbell/github/yggdrasil-training-data/dpo_pairs_v7.jsonl")

META_KEYS = {"_source", "_error_type", "_orig_source", "_prompt_hash", "_src_file"}


def _pair_hash(record: dict) -> str:
    key = record.get("prompt", "")[:200] + record.get("chosen", "")[:100]
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def load_jsonl(path: Path, label: str) -> list[dict]:
    if not path.exists():
        print(f"  [warn] not found: {path} — skipping {label}", file=sys.stderr)
        return []
    records = []
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("prompt") and r.get("chosen") and r.get("rejected"):
                records.append(r)
        except json.JSONDecodeError:
            continue
    print(f"  {label}: {len(records)} valid pairs from {path.name}")
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-meta", action="store_true", help="Keep _source/_error_type fields")
    args = parser.parse_args()

    print("── Yggdrasil v7 Merge  b17:V7MG1 ──")
    print()

    all_pairs: list[dict] = []
    all_pairs.extend(load_jsonl(REGEN_FILE, "regen"))
    all_pairs.extend(load_jsonl(NEW_FILE,   "new"))

    print(f"\nTotal before dedup: {len(all_pairs)}")

    # Deduplicate
    seen: set[str] = set()
    deduped: list[dict] = []
    for p in all_pairs:
        h = _pair_hash(p)
        if h not in seen:
            seen.add(h)
            deduped.append(p)

    print(f"Total after dedup:  {len(deduped)} ({len(all_pairs) - len(deduped)} removed)")

    # Stats by source
    source_counts = Counter(p.get("_source", "unknown") for p in deduped)
    print("\n── By source ──")
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {src:<30} {count:>5}")

    # Strip meta if not keeping
    output_pairs = []
    for p in deduped:
        if args.keep_meta:
            output_pairs.append(p)
        else:
            output_pairs.append({k: v for k, v in p.items() if k not in META_KEYS})

    # Write
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        for p in output_pairs:
            f.write(json.dumps(p) + "\n")

    size_kb = OUTPUT.stat().st_size // 1024
    print(f"\nWritten: {OUTPUT}")
    print(f"  {len(output_pairs)} pairs  {size_kb} KB")
    print()
    print("Next: upload yggdrasil-training-data/ to Kaggle as rudi193/yggdrasil-v7")
    print("      then run yggdrasil_kaggle_v7.ipynb")


if __name__ == "__main__":
    main()
