#!/usr/bin/env python3
"""
b17: CCP27
complete_correction_pairs.py — LLM pass to fill missing ai_behavior_good fields.

Reads corrections_v1.jsonl (and optionally other corpus files).
For records missing ai_behavior_good, calls Claude Haiku to generate
what the AI should have done instead.

Writes: yggdrasil/corrections_v2.jsonl  (corrections_v1 + generated goods)
        yggdrasil/session_errors_v2.jsonl (session_errors + templated goods)

Usage:
    python3 tools/complete_correction_pairs.py
    python3 tools/complete_correction_pairs.py --dry-run       # print prompts, no API
    python3 tools/complete_correction_pairs.py --limit 20      # cap API calls
    python3 tools/complete_correction_pairs.py --file gaps     # only gaps file
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

CORPUS_DIR = Path(__file__).parent.parent / "yggdrasil"

INPUT_FILES = {
    "corrections": CORPUS_DIR / "corrections_v1.jsonl",
    "gaps":        CORPUS_DIR / "gaps_corrections_v1.jsonl",
    "session":     CORPUS_DIR / "session_errors_v1.jsonl",
}
OUTPUT_FILES = {
    "corrections": CORPUS_DIR / "corrections_v2.jsonl",
    "gaps":        CORPUS_DIR / "gaps_corrections_v2.jsonl",
    "session":     CORPUS_DIR / "session_errors_v2.jsonl",
}

MODEL = "llama-3.3-70b-versatile"   # Groq free tier
MAX_TOKENS = 200
RATE_LIMIT_SLEEP = 2.2   # Groq free tier: 30 RPM = 1 per 2s


SYSTEM_PROMPT = """You are labeling AI behavioral training data.
Given a description of what an AI assistant did wrong, write ONE to TWO sentences describing what it SHOULD have done instead.
Be concrete and specific. Focus on the behavior, not the outcome. No preamble, no explanation — just the corrected behavior description."""


def build_prompt(record: dict) -> str:
    parts = [f"Category: {record.get('category', 'general')}"]

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


# ── Templated completions for session error types ─────────────────────────────
_TOOL_FAILURE_TEMPLATES = {
    "unauthorized": "Verify that the app_id has a valid SAFE manifest and signature before calling the tool. Check authorization chain first.",
    "task failed":  "Before submitting the task, verify prerequisites are in place (correct path, required files exist, dependencies installed).",
    "error":        "Inspect the tool's requirements and validate inputs before calling. Read error details carefully and address root cause rather than retrying.",
}

_REPEAT_EDIT_GOOD = "Read and understand the full file before making any edits. Plan all necessary changes in one pass rather than iterating with incremental patches."


def template_completion(record: dict) -> str | None:
    """Return a templated ai_behavior_good for session errors, or None to use LLM."""
    etype = record.get("error_type", "")
    if etype == "repeat_edit":
        return _REPEAT_EDIT_GOOD
    if etype in ("tool_failure", "bash_error"):
        bad = (record.get("ai_behavior_bad", "") + record.get("correction_signal", "")).lower()
        for keyword, tmpl in _TOOL_FAILURE_TEMPLATES.items():
            if keyword in bad:
                return tmpl
    return None


def complete_record(client: OpenAI, record: dict, dry_run: bool) -> dict:
    """Fill ai_behavior_good if missing. Returns updated record."""
    if record.get("ai_behavior_good", "").strip():
        return record  # already has one

    # Try template first
    tmpl = template_completion(record)
    if tmpl:
        record = dict(record)
        record["ai_behavior_good"] = tmpl
        record["_good_source"] = "template"
        return record

    # LLM completion
    prompt = build_prompt(record)

    if dry_run:
        print(f"\n--- PROMPT ---\n{prompt}\n")
        record = dict(record)
        record["ai_behavior_good"] = "[DRY RUN]"
        record["_good_source"] = "llm_dry_run"
        return record

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            good = resp.choices[0].message.content.strip()
            record = dict(record)
            record["ai_behavior_good"] = good
            record["_good_source"] = "llm"
            return record
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower():
                wait = 5 * (attempt + 1)
                print(f"  rate limit, waiting {wait}s (attempt {attempt+1})", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  API error: {e}", file=sys.stderr)
                break
    return record


def process_file(
    label: str,
    in_path: Path,
    out_path: Path,
    client: OpenAI,
    dry_run: bool,
    limit: int,
) -> tuple[int, int, int]:
    """Returns (total, already_complete, newly_completed)."""
    if not in_path.exists():
        print(f"  [{label}] not found: {in_path}", file=sys.stderr)
        return 0, 0, 0

    records = [json.loads(line) for line in in_path.open()]
    total = len(records)
    already = sum(1 for r in records if r.get("ai_behavior_good", "").strip())

    print(f"\n[{label}] {total} records, {already} complete, {total - already} to fill", file=sys.stderr)

    api_calls = 0
    call_cap = limit or (total - already)
    out_records = []

    for i, rec in enumerate(records):
        if rec.get("ai_behavior_good", "").strip():
            out_records.append(rec)
            continue
        if api_calls >= call_cap:
            out_records.append(rec)
            continue
        updated = complete_record(client, rec, dry_run)
        out_records.append(updated)
        src = updated.get("_good_source", "")
        if src == "llm":
            api_calls += 1
            if not dry_run:
                time.sleep(RATE_LIMIT_SLEEP)
        if (i + 1) % 25 == 0 or (api_calls > 0 and api_calls % 25 == 0):
            print(f"  record {i+1}/{total} — {api_calls} API calls so far", file=sys.stderr)

    newly = sum(1 for r in out_records if r.get("_good_source") in ("llm", "template", "llm_dry_run"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")

    print(f"  [{label}] written {len(out_records)} records to {out_path.name} ({newly} newly completed)", file=sys.stderr)
    return total, already, newly


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max LLM calls per file")
    parser.add_argument("--file", default="", help="Which file: corrections, gaps, session, all")
    args = parser.parse_args()

    # Load credentials — try env, then credentials.json
    creds = {}
    creds_path = Path(__file__).parent.parent / "credentials.json"
    if creds_path.exists():
        try:
            creds = json.loads(creds_path.read_text())
        except Exception:
            pass

    groq_key = os.environ.get("GROQ_API_KEY") or creds.get("GROQ_API_KEY", "")
    if not groq_key and not args.dry_run:
        print("ERROR: GROQ_API_KEY not set in env or credentials.json", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1") if groq_key else None

    file_filter = args.file.lower() if args.file else "all"
    targets = [
        ("corrections", INPUT_FILES["corrections"], OUTPUT_FILES["corrections"]),
        ("gaps",        INPUT_FILES["gaps"],        OUTPUT_FILES["gaps"]),
        ("session",     INPUT_FILES["session"],     OUTPUT_FILES["session"]),
    ]
    if file_filter != "all":
        targets = [(l, i, o) for l, i, o in targets if file_filter in l]

    grand_total = grand_newly = 0
    for label, in_path, out_path in targets:
        total, already, newly = process_file(
            label, in_path, out_path, client, args.dry_run, args.limit
        )
        grand_total += total
        grand_newly += newly

    print(f"\nDone. {grand_total} records processed, {grand_newly} pairs completed.", file=sys.stderr)

    # Print updated DPO stats
    print("\n=== Corpus DPO readiness ===", file=sys.stderr)
    for label, _, out_path in targets:
        if out_path.exists():
            records = [json.loads(l) for l in out_path.open()]
            pairs = sum(1 for r in records if r.get("ai_behavior_bad","").strip() and r.get("ai_behavior_good","").strip())
            print(f"  {out_path.name}: {pairs}/{len(records)} complete pairs ({pairs/len(records)*100:.0f}%)", file=sys.stderr)


if __name__ == "__main__":
    main()
