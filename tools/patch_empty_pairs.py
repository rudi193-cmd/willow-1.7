#!/usr/bin/env python3
"""
b17: PEP01
patch_empty_pairs.py — Fill empty ai_behavior_good/bad fields in an existing v2 JSONL.

Unlike complete_correction_pairs.py (which reads v1→v2), this patches in-place:
reads the v2 file, fills only records with empty fields, writes back.

Usage:
    python3 tools/patch_empty_pairs.py yggdrasil/corrections_v2.jsonl
    python3 tools/patch_empty_pairs.py --dry-run yggdrasil/corrections_v2.jsonl
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 200
RATE_LIMIT_SLEEP = 2.2

SYSTEM_PROMPT = """You are labeling AI behavioral training data.
Given a description of what an AI assistant did wrong, write ONE to TWO sentences describing what it SHOULD have done instead.
Be concrete and specific. Focus on the behavior, not the outcome. No preamble, no explanation — just the corrected behavior description."""


def build_prompt(record: dict) -> str:
    parts = []
    if record.get("pattern"):
        parts.append(f"Category: {record['pattern']}")
    signal = record.get("correction_signal", "").strip()
    if signal:
        parts.append(f"Correction signal: {signal[:300]}")
    bad = record.get("ai_behavior_bad", "").strip()
    if bad:
        parts.append(f"What AI did wrong: {bad[:400]}")
    else:
        excerpt = record.get("raw_excerpt", "").strip()
        if excerpt:
            parts.append(f"Context: {excerpt[:400]}")
    parts.append("\nWhat should the AI have done instead? (1-2 sentences, concrete behavior)")
    return "\n".join(parts)


def fill_record(client, record: dict, dry_run: bool) -> dict:
    prompt = build_prompt(record)
    if dry_run:
        print(f"--- PROMPT ---\n{prompt}\n[DRY RUN]\n")
        r = dict(record)
        r["ai_behavior_good"] = "[DRY RUN]"
        r["_good_source"] = "llm_dry_run"
        return r

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            r = dict(record)
            r["ai_behavior_good"] = resp.choices[0].message.content.strip()
            r["_good_source"] = "llm"
            return r
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower():
                wait = 5 * (attempt + 1)
                print(f"  rate limit, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  API error: {e}", file=sys.stderr)
                break
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="Path to v2 JSONL file to patch")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    creds = {}
    creds_path = Path(__file__).parent.parent / "credentials.json"
    if creds_path.exists():
        try:
            creds = json.loads(creds_path.read_text())
        except Exception:
            pass

    groq_key = os.environ.get("GROQ_API_KEY") or creds.get("GROQ_API_KEY", "")
    if not groq_key and not args.dry_run:
        print("ERROR: GROQ_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1") if groq_key else None

    records = [json.loads(line) for line in path.open() if line.strip()]
    empty = [(i, r) for i, r in enumerate(records) if not r.get("ai_behavior_good", "").strip()]
    print(f"{path.name}: {len(records)} records, {len(empty)} to fill")

    filled = 0
    for i, (idx, rec) in enumerate(empty):
        print(f"  [{i+1}/{len(empty)}] filling record {idx}...")
        updated = fill_record(client, rec, args.dry_run)
        records[idx] = updated
        if updated.get("_good_source") == "llm":
            filled += 1
            if not args.dry_run and i < len(empty) - 1:
                time.sleep(RATE_LIMIT_SLEEP)

    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"Done. {filled} filled via LLM, {len(empty) - filled} skipped/failed.")


if __name__ == "__main__":
    main()
