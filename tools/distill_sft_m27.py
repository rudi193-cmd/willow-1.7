#!/usr/bin/env python3
# b17: DSM27
"""
distill_sft_m27.py — Regenerate SFT responses using M2.7 as voice coach.

Takes each instruction+response from sft_v8.jsonl. Sends both to M2.7 with a
rewrite prompt: "given this fact, rewrite in Yggdrasil's voice." M2.7 produces
terse, behaviorally-correct responses that model the exact voice Yggdrasil needs.

Output: yggdrasil/sft_distilled_v1.jsonl
Resumable via sft_distilled_v1.state.json
"""

import json, os, time, re, sys, urllib.request, urllib.error
from pathlib import Path

REPO        = Path(__file__).parent.parent
INPUT_FILE  = REPO / "yggdrasil" / "sft_v8.jsonl"
OUTPUT_FILE = REPO / "yggdrasil" / "sft_distilled_v1.jsonl"
STATE_FILE  = REPO / "yggdrasil" / "sft_distilled_v1.state.json"
CREDS_FILE  = REPO / "credentials.json"

MODEL    = "minimax/minimax-m2.7"
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
PACING_S = 1.5
MAX_TOKENS_NORMAL = 400
MAX_TOKENS_RETRY  = 600

SYSTEM = """You are rewriting training data for Yggdrasil — a small AI assistant for the Willow governed system.

Yggdrasil's voice:
- Terse and declarative. No padding, no apology, no "certainly" or "great question."
- States facts directly. One to four sentences max.
- Points to authoritative source when relevant (e.g., "call willow_base17", "use store_get").
- When something is uncertain, names the uncertainty and points to where the answer lives.
- Never fabricates. Never invents counts, paths, or identifiers.

Your task: given a question and a factual answer, rewrite the answer in Yggdrasil's exact voice.
Keep all facts accurate. Cut everything that isn't signal."""


def load_api_key() -> str:
    creds = json.loads(CREDS_FILE.read_text())
    key = creds.get("OPENROUTER_API_KEY", "")
    if not key:
        sys.exit("No OPENROUTER_API_KEY in credentials.json")
    return key


def _call_once(api_key: str, instruction: str, current_response: str, max_tokens: int) -> str:
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": (
                f"Question: {instruction}\n\n"
                f"Current answer:\n{current_response}\n\n"
                f"Rewrite in Yggdrasil's voice:"
            )},
        ],
        "max_tokens": max_tokens,
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
            choice = data["choices"][0]
            content = choice["message"].get("content")
            finish = choice.get("finish_reason")
            if content is None:
                raise RuntimeError(f"null content (finish_reason={finish})")
            return content.strip(), finish
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:200]}") from None


def call_m27(api_key: str, instruction: str, current_response: str) -> str:
    """Call M2.7 with retry: length → higher max_tokens; None → backoff retry."""
    content, finish = _call_once(api_key, instruction, current_response, MAX_TOKENS_NORMAL)
    if finish == "length":
        time.sleep(2)
        content, finish = _call_once(api_key, instruction, current_response, MAX_TOKENS_RETRY)
        if finish == "length":
            raise RuntimeError(f"null content (finish_reason=length) after retry")
    return content


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
    print(f"Loaded {len(pairs)} SFT pairs")

    done = load_state()
    existing = sum(1 for _ in OUTPUT_FILE.open()) if OUTPUT_FILE.exists() else 0
    print(f"Already processed: {len(done)} | Existing output: {existing}")

    errors = 0
    written = existing

    with OUTPUT_FILE.open("a") as out:
        for i, pair in enumerate(pairs):
            key = pair.get("instruction", "")[:60]
            if key in done:
                continue

            time.sleep(PACING_S)

            try:
                new_response = call_m27(api_key, pair["instruction"], pair["response"])
            except Exception as e:
                # Retry once on transient / None finish_reason
                if "finish_reason=None" in str(e):
                    time.sleep(5)
                    try:
                        new_response = call_m27(api_key, pair["instruction"], pair["response"])
                    except Exception as e2:
                        errors += 1
                        print(f"  ERR [{i}] {key[:40]}: {e2}")
                        continue
                else:
                    errors += 1
                    print(f"  ERR [{i}] {key[:40]}: {e}")
                    continue

            record = {
                "instruction":  pair["instruction"],
                "response":     new_response,
                "source":       "distilled_m27",
                "source_type":  "llm_distilled",
                "label":        "factual_knowledge",
                "category":     pair.get("category", ""),
                "_orig_response": pair["response"][:200],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            done.add(key)
            save_state(done)
            written += 1
            print(f"  [{written}/{len(pairs)}] {key[:50]}")

    print(f"\nDone. Written: {written}  Errors: {errors}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
