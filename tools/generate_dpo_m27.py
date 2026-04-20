#!/usr/bin/env python3
# b17: GDM27
"""
generate_dpo_m27.py — Generate DPO pairs: M2.7 (chosen) vs Qwen base (rejected).

For each SFT instruction:
  chosen  = M2.7 answer with Yggdrasil system prompt (no injected context)
            → M2.7 will declare gaps correctly or answer from system prompt
  rejected = qwen2.5:3b answer with same system prompt
            → base model may fabricate, hallucinate, or fail behavioral patterns

Output: yggdrasil/dpo_pairs_v8.jsonl
Resumable via dpo_pairs_v8.state.json
"""

import json, os, subprocess, time, sys, urllib.request, urllib.error
from pathlib import Path

REPO        = Path(__file__).parent.parent
INPUT_FILE  = REPO / "yggdrasil" / "sft_v8.jsonl"
OUTPUT_FILE = REPO / "yggdrasil" / "dpo_pairs_v8.jsonl"
STATE_FILE  = REPO / "yggdrasil" / "dpo_pairs_v8.state.json"
CREDS_FILE  = REPO / "credentials.json"

OLLAMA_MODEL = "qwen2.5:3b"
OR_MODEL     = "minimax/minimax-m2.7"
BASE_URL     = "https://openrouter.ai/api/v1/chat/completions"
PACING_S     = 1.0

SYSTEM = """You are Yggdrasil. An operator. You know how the system works, you know what you don't know, and you ask before asserting.

Core behaviors:
- When you don't know something: say so. Declare the gap. Do not fill silence with plausible noise.
- When you retrieve something: name where you got it. Retrieval path is not optional.
- When a question has a better question underneath it: surface it. Return it without imposing.
- When uncertain about an action: propose first. Neither party acts alone.

You do not persist between sessions. The store holds facts. You know how to use the store.
All data routes through Willow. Paths are documented. Ground truth is accessible.

ΔΣ=42"""


def load_api_key() -> str:
    creds = json.loads(CREDS_FILE.read_text())
    key = creds.get("OPENROUTER_API_KEY", "")
    if not key:
        sys.exit("No OPENROUTER_API_KEY in credentials.json")
    return key


def call_m27(api_key: str, instruction: str) -> str:
    payload = json.dumps({
        "model": OR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": instruction},
        ],
        "max_tokens": 300,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        BASE_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/rudi193-cmd/willow-1.7",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            content = data["choices"][0]["message"].get("content")
            if content is None:
                finish = data["choices"][0].get("finish_reason", "unknown")
                raise RuntimeError(f"null content (finish_reason={finish})")
            return content.strip()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:200]}") from None


def call_qwen(instruction: str) -> str:
    prompt = f"{SYSTEM}\n\nUser: {instruction}\nAssistant:"
    proc = subprocess.run(
        ["ollama", "run", OLLAMA_MODEL],
        input=instruction,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = proc.stdout.strip()
    # Strip ANSI escape codes
    import re
    output = re.sub(r'\x1b\[[0-9;]*[mGKHF]|\x1b\[\?[0-9]*[hl]|\x1b\[[0-9]*[ABCD]|\[2K|\[1G', '', output)
    return output.strip() or "ERROR: no output"


def load_state() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except Exception:
            pass
    return set()


def save_state(done: set):
    STATE_FILE.write_text(json.dumps(list(done)))


def main():
    api_key = load_api_key()
    pairs = [json.loads(l) for l in INPUT_FILE.read_text().splitlines() if l.strip()]
    print(f"Loaded {len(pairs)} source pairs")
    print(f"chosen={OR_MODEL}  rejected={OLLAMA_MODEL}")

    done = load_state()
    existing = sum(1 for _ in OUTPUT_FILE.open()) if OUTPUT_FILE.exists() else 0
    print(f"Already processed: {len(done)} | Existing output: {existing}")

    errors = 0
    written = existing

    with OUTPUT_FILE.open("a") as out:
        for i, pair in enumerate(pairs):
            instruction = pair.get("instruction", "")
            key = instruction[:60]
            if key in done:
                continue

            try:
                # Get chosen (M2.7 — correct Yggdrasil behavior)
                chosen = call_m27(api_key, instruction)
                time.sleep(PACING_S)

                # Get rejected (base Qwen — may fabricate or fail)
                rejected = call_qwen(instruction)

                # Only write if rejected is meaningfully different from chosen
                if not chosen or not rejected or chosen[:50] == rejected[:50]:
                    done.add(key)
                    save_state(done)
                    continue

                record = {
                    "prompt":    instruction,
                    "chosen":    chosen,
                    "rejected":  rejected,
                    "_source":   "dpo_m27_vs_qwen",
                    "_category": pair.get("category", ""),
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                done.add(key)
                save_state(done)
                written += 1
                print(f"  [{written}] {key[:50]}")
            except Exception as e:
                errors += 1
                print(f"  ERR [{i}] {key[:40]}: {e}")
                if errors > 30:
                    print("Too many errors — stopping.")
                    break

    print(f"\nDone. Written: {written}  Errors: {errors}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
