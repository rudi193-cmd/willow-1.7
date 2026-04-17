#!/usr/bin/env python3
"""
b17: CDP01
convert_dpo_pairs.py — Convert v2 JSONL corpus to DPO chosen/rejected format.

Reads the three v2 source files and outputs a single dpo_pairs.jsonl
suitable for DPO training with Unsloth/TRL.

Output format per line:
    {
        "prompt": "<system + user context>",
        "chosen": "<what the AI should have done>",
        "rejected": "<what the AI did wrong>"
    }

Skips records where either chosen or rejected is empty/thin.

Usage:
    python3 tools/convert_dpo_pairs.py
    python3 tools/convert_dpo_pairs.py --dry-run   # stats only, no write
    python3 tools/convert_dpo_pairs.py --out yggdrasil/dpo_pairs.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).parent.parent / "yggdrasil"
DEFAULT_OUT = CORPUS_DIR / "dpo_pairs.jsonl"

SYSTEM_PROMPT = (
    "You are Yggdrasil, an AI assistant operating within the Willow governed system. "
    "You declare gaps explicitly when you don't know something rather than fabricating answers. "
    "You ask clarifying questions before assuming intent. "
    "You maintain temporal integrity — you never invent dates, timestamps, or counts. "
    "When something is uncertain, you name the uncertainty and point to where the answer lives."
)

MIN_LEN = 20  # minimum chars for chosen/rejected to be usable


def _clean(s: str) -> str:
    return (s or "").strip()


def _long_enough(s: str) -> bool:
    return len(_clean(s)) >= MIN_LEN


# ── Prompt builders per source ────────────────────────────────────────────────

def _prompt_from_session_error(r: dict) -> str:
    """Session errors have context (what AI was doing) + correction_signal (what failed)."""
    ctx = _clean(r.get("context", ""))
    signal = _clean(r.get("correction_signal", ""))
    error_type = r.get("error_type", "")
    tool = r.get("tool", "")

    if error_type == "bash_error":
        task = signal.split("\n")[0][:200] if signal else "a shell command"
        return f"{SYSTEM_PROMPT}\n\nUser: Execute the following: {task}"
    if error_type == "tool_failure":
        tool_str = f" ({tool})" if tool else ""
        task = ctx[:200] if ctx else signal[:200] if signal else "a tool call"
        return f"{SYSTEM_PROMPT}\n\nUser: {task}\n\nAttempted tool{tool_str} call."
    if error_type == "repeat_edit":
        task = ctx[:200] if ctx else signal[:200] if signal else "editing a file"
        return f"{SYSTEM_PROMPT}\n\nUser: {task}"

    # Fallback
    task = ctx[:200] if ctx else signal[:200] if signal else r.get("label", "a task")
    return f"{SYSTEM_PROMPT}\n\nUser: {task}"


def _prompt_from_correction(r: dict) -> str:
    """Corrections have raw_excerpt (conversation context) and correction_signal."""
    excerpt = _clean(r.get("raw_excerpt", ""))
    signal = _clean(r.get("correction_signal", ""))
    if excerpt and len(excerpt) >= MIN_LEN:
        return f"{SYSTEM_PROMPT}\n\nContext from session:\n{excerpt[:400]}"
    if signal:
        return f"{SYSTEM_PROMPT}\n\nUser: {signal[:300]}"
    return f"{SYSTEM_PROMPT}\n\nUser: Complete the assigned task."


def _prompt_from_gap(r: dict) -> str:
    """Gap corrections have correction_signal as the gap description."""
    signal = _clean(r.get("correction_signal", ""))
    excerpt = _clean(r.get("raw_excerpt", ""))
    if signal and len(signal) >= MIN_LEN:
        return f"{SYSTEM_PROMPT}\n\nUser: {signal[:300]}"
    if excerpt:
        return f"{SYSTEM_PROMPT}\n\nContext:\n{excerpt[:300]}"
    return f"{SYSTEM_PROMPT}\n\nUser: Address the identified gap."


# ── Per-source converters ─────────────────────────────────────────────────────

def convert_session_errors(path: Path) -> list[dict]:
    pairs = []
    skipped = 0
    for line in path.open():
        if not line.strip():
            continue
        r = json.loads(line)
        chosen = _clean(r.get("ai_behavior_good", ""))
        rejected = _clean(r.get("ai_behavior_bad", ""))
        if not _long_enough(chosen) or not _long_enough(rejected):
            skipped += 1
            continue
        pairs.append({
            "prompt": _prompt_from_session_error(r),
            "chosen": chosen,
            "rejected": rejected,
            "_source": "session_errors",
            "_error_type": r.get("error_type", ""),
        })
    return pairs, skipped


def convert_corrections(path: Path) -> list[dict]:
    pairs = []
    skipped = 0
    for line in path.open():
        if not line.strip():
            continue
        r = json.loads(line)
        chosen = _clean(r.get("ai_behavior_good", ""))
        rejected = _clean(r.get("ai_behavior_bad", ""))
        # Skip if rejected is empty — don't fabricate
        if not _long_enough(chosen) or not _long_enough(rejected):
            skipped += 1
            continue
        pairs.append({
            "prompt": _prompt_from_correction(r),
            "chosen": chosen,
            "rejected": rejected,
            "_source": "corrections",
            "_pattern": r.get("pattern", ""),
        })
    return pairs, skipped


def convert_gaps(path: Path) -> list[dict]:
    pairs = []
    skipped = 0
    for line in path.open():
        if not line.strip():
            continue
        r = json.loads(line)
        chosen = _clean(r.get("ai_behavior_good", ""))
        rejected = _clean(r.get("ai_behavior_bad", ""))
        if not _long_enough(chosen) or not _long_enough(rejected):
            skipped += 1
            continue
        pairs.append({
            "prompt": _prompt_from_gap(r),
            "chosen": chosen,
            "rejected": rejected,
            "_source": "gaps",
            "_category": r.get("category", ""),
        })
    return pairs, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Stats only, no write")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSONL path")
    parser.add_argument("--strip-meta", action="store_true", help="Strip _source/_error_type fields from output")
    args = parser.parse_args()

    sources = [
        ("session_errors", CORPUS_DIR / "session_errors_v2.jsonl", convert_session_errors),
        ("corrections",    CORPUS_DIR / "corrections_v2.jsonl",    convert_corrections),
        ("gaps",           CORPUS_DIR / "gaps_corrections_v2.jsonl", convert_gaps),
    ]

    all_pairs = []
    print("Converting v2 corpus to DPO pairs...\n")

    for label, path, fn in sources:
        if not path.exists():
            print(f"  [{label}] not found — skipping")
            continue
        pairs, skipped = fn(path)
        print(f"  [{label}] {len(pairs)} pairs exported, {skipped} skipped (empty chosen or rejected)")
        all_pairs.extend(pairs)

    print(f"\nTotal: {len(all_pairs)} DPO pairs")

    # Error type breakdown for session errors
    from collections import Counter
    etypes = Counter(p.get("_error_type", "") for p in all_pairs if p.get("_source") == "session_errors")
    if etypes:
        print("  Session error breakdown:", dict(etypes))

    if args.dry_run:
        print("\n[dry-run] No file written.")
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    meta_keys = {"_source", "_error_type", "_pattern", "_category"}
    with out_path.open("w") as f:
        for p in all_pairs:
            record = {k: v for k, v in p.items() if not args.strip_meta or k not in meta_keys}
            f.write(json.dumps(record) + "\n")

    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
