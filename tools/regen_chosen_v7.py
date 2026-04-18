#!/usr/bin/env python3
"""
regen_chosen_v7.py — Regenerate chosen responses for all existing DPO pairs.

Reads dpo_pairs.jsonl + dpo_pairs_kart.jsonl (DPO-format only).
Calls fleet LLM with full Willow context to write Willow-specific chosen responses.
Checkpoints per pair — resumable. Skips pairs already in checkpoint.

Output: yggdrasil/dpo_pairs_v7_regen.jsonl

Usage:
  python3 tools/regen_chosen_v7.py
  python3 tools/regen_chosen_v7.py --dry-run
  python3 tools/regen_chosen_v7.py --limit 50

Config (env):
  WILLOW_V7_PROVIDER   groq | sambanova | openrouter  (default: groq)
  WILLOW_V7_MODEL      model override
  GROQ_API_KEY / SAMBANOVA_API_KEY / OPENROUTER_API_KEY

b17: V7RG1
ΔΣ=42
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

WILLOW_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(WILLOW_ROOT))

from tools.v7_llm import call_llm, provider_info
from tools.v7_context import WILLOW_CONTEXT, CHOSEN_PROMPT_TEMPLATE

INPUT_FILES = [
    WILLOW_ROOT / "yggdrasil" / "dpo_pairs.jsonl",
    WILLOW_ROOT / "yggdrasil" / "dpo_pairs_kart.jsonl",
]
CHECKPOINT = WILLOW_ROOT / "yggdrasil" / "dpo_pairs_v7_regen.jsonl"


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _extract_user_part(prompt: str) -> str:
    """Strip embedded system prompt from prompt field."""
    marker = "\n\nUser: "
    idx = prompt.find(marker)
    if idx != -1:
        return prompt[idx + len(marker):]
    # Fallback: strip first paragraph if it looks like a system prompt
    lines = prompt.strip().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("User:"):
            return "\n".join(lines[i:]).removeprefix("User:").strip()
    return prompt


def _is_dpo_pair(record: dict) -> bool:
    """True if record has both chosen and rejected (not an SFT record)."""
    chosen = record.get("chosen", "").strip()
    rejected = record.get("rejected", "").strip()
    return bool(chosen) and bool(rejected)


def load_pairs() -> list[dict]:
    pairs = []
    for path in INPUT_FILES:
        if not path.exists():
            print(f"  [warn] not found: {path}", file=sys.stderr)
            continue
        count = 0
        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _is_dpo_pair(r):
                r["_src_file"] = path.name
                pairs.append(r)
                count += 1
        print(f"  {path.name}: {count} DPO pairs loaded")
    return pairs


def load_checkpoint() -> set[str]:
    done = set()
    if CHECKPOINT.exists():
        for line in CHECKPOINT.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if "_prompt_hash" in r:
                    done.add(r["_prompt_hash"])
            except json.JSONDecodeError:
                continue
    return done


def regen_chosen(pair: dict) -> str:
    user_part = _extract_user_part(pair["prompt"])
    rejected = pair.get("rejected", "")[:300]
    prompt = CHOSEN_PROMPT_TEMPLATE.format(
        context=WILLOW_CONTEXT,
        user_part=user_part[:600],
        rejected=rejected,
    )
    return call_llm(prompt, temperature=0.35, max_tokens=250)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No LLM calls — show stats only")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N pairs")
    args = parser.parse_args()

    print(f"── Yggdrasil v7 Chosen Regeneration  b17:V7RG1 ──")
    print(f"Provider: {provider_info()}")
    print(f"Checkpoint: {CHECKPOINT}")
    print()

    print("Loading pairs...")
    pairs = load_pairs()
    print(f"Total DPO pairs: {len(pairs)}")

    done = load_checkpoint()
    print(f"Already checkpointed: {len(done)}")

    pending = [p for p in pairs if _prompt_hash(p["prompt"]) not in done]
    print(f"Pending: {len(pending)}")

    if args.limit:
        pending = pending[: args.limit]
        print(f"Limit applied: {len(pending)}")

    if args.dry_run:
        print("\n[dry-run] No LLM calls. Done.")
        return

    if not pending:
        print("\nNothing to do.")
        return

    print()
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)

    with CHECKPOINT.open("a", encoding="utf-8") as out:
        for i, pair in enumerate(pending, 1):
            ph = _prompt_hash(pair["prompt"])
            try:
                new_chosen = regen_chosen(pair)
                record = {
                    "prompt": pair["prompt"],
                    "chosen": new_chosen,
                    "rejected": pair["rejected"],
                    "_source": "regen_v7",
                    "_orig_source": pair.get("_source", ""),
                    "_error_type": pair.get("_error_type", ""),
                    "_prompt_hash": ph,
                }
                out.write(json.dumps(record) + "\n")
                out.flush()
                print(f"[{i}/{len(pending)}] {ph} — done  ({pair.get('_src_file', '')})")
            except Exception as e:
                print(f"[{i}/{len(pending)}] {ph} — ERROR: {e}", file=sys.stderr)

    print(f"\nDone. Checkpoint: {CHECKPOINT}")


if __name__ == "__main__":
    main()
