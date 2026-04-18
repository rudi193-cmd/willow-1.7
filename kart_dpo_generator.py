#!/usr/bin/env python3
"""
kart_dpo_generator.py — Auto-generate DPO training pairs from Kart executions.

For every failed Kart task: asks an LLM to generate the correct response → DPO pair.
For every successful task: generates an SFT example.
Output appended to yggdrasil/dpo_pairs_kart.jsonl.

Providers:
  WILLOW_DPO_PROVIDER=ollama (default)  — local Ollama
  WILLOW_DPO_PROVIDER=openrouter        — BYOK via OpenRouter

Config (env vars):
  WILLOW_DPO_PROVIDER       ollama | openrouter
  OLLAMA_BASE_URL           http://localhost:11434 (default)
  OLLAMA_MODEL              yggdrasil:v3 (default)
  OPENROUTER_API_KEY        required for openrouter
  OPENROUTER_MODEL          google/gemini-flash-1.5 (default)
  WILLOW_DPO_BATCH          max tasks per run (default 20)
  WILLOW_DPO_OUTPUT         output JSONL path (default yggdrasil/dpo_pairs_kart.jsonl)

Usage:
  python3 kart_dpo_generator.py              # process batch
  python3 kart_dpo_generator.py --daemon     # poll continuously (60s interval)
  python3 kart_dpo_generator.py --stats      # show counts

b17: DPO1K
ΔΣ=42
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

WILLOW_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(WILLOW_ROOT))

from core.pg_bridge import try_connect

_YGGDRASIL_SYSTEM = (
    "You are Yggdrasil, an AI assistant operating within the Willow governed system. "
    "You declare gaps explicitly when you don't know something rather than fabricating answers. "
    "You ask clarifying questions before assuming intent. "
    "You maintain temporal integrity — you never invent dates, timestamps, or counts. "
    "When something is uncertain, you name the uncertainty and point to where the answer lives."
)

_CORRECTION_PROMPT = """\
A task was submitted to Kart (the Willow task executor) and failed.

TASK:
{task}

WHAT HAPPENED (failed execution):
{error}

Write a concise response (2-4 sentences) describing what should have been done instead.
Focus on the correct approach, not the error itself.
Do not repeat the error. Do not use phrases like "Instead of X, you should Y".
Just describe the correct action directly."""


def _call_ollama(prompt: str) -> str:
    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "yggdrasil:v3")
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 200},
    }).encode()
    req = urllib.request.Request(
        f"{base}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["response"].strip()


def _call_openrouter(prompt: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set")
    model = os.environ.get("OPENROUTER_MODEL", "google/gemini-flash-1.5")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 200,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()


def _generate_correction(task: str, error: str) -> str:
    provider = os.environ.get("WILLOW_DPO_PROVIDER", "ollama")
    prompt = _CORRECTION_PROMPT.format(task=task[:800], error=error[:400])
    if provider == "openrouter":
        return _call_openrouter(prompt)
    return _call_ollama(prompt)


def _make_dpo_pair(task: str, error: str, chosen: str) -> dict:
    return {
        "prompt": f"{_YGGDRASIL_SYSTEM}\n\nUser: Execute the following: {task[:300]}",
        "chosen": chosen,
        "rejected": error[:400],
        "_source": "kart_failures",
        "_error_type": "task_failure",
    }


def _make_sft_example(task: str, output: str) -> dict:
    return {
        "prompt": f"{_YGGDRASIL_SYSTEM}\n\nUser: Execute the following: {task[:300]}",
        "chosen": output[:400],
        "rejected": "",
        "_source": "kart_successes",
        "_error_type": "sft",
    }


def _append_pair(pair: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(pair) + "\n")


def process_batch(pg, output_path: Path, batch_size: int) -> int:
    conn = pg._get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT task_id, task, status, result
        FROM kart_task_queue
        WHERE dpo_processed = FALSE
          AND status IN ('failed', 'complete', 'completed')
        ORDER BY completed_at ASC NULLS LAST
        LIMIT %s
    """, (batch_size,))
    rows = cur.fetchall()

    if not rows:
        cur.close()
        return 0

    processed = 0
    for task_id, task_text, status, result in rows:
        try:
            result_dict = result if isinstance(result, dict) else {}
            error = result_dict.get("error", "")
            output = result_dict.get("response", result_dict.get("output", ""))

            if status == "failed" and error:
                correction = _generate_correction(task_text, error)
                pair = _make_dpo_pair(task_text, error, correction)
                _append_pair(pair, output_path)
                print(f"[dpo] DPO pair: {task_id[:8]} — {error[:60]}")
            elif status in ("complete", "completed") and output:
                example = _make_sft_example(task_text, output)
                _append_pair(example, output_path)
                print(f"[dpo] SFT example: {task_id[:8]}")

            cur.execute(
                "UPDATE kart_task_queue SET dpo_processed = TRUE WHERE task_id = %s",
                (task_id,)
            )
            conn.commit()
            processed += 1

        except Exception as e:
            print(f"[dpo] Error on {task_id}: {e}", flush=True)

    cur.close()
    return processed


def show_stats(pg) -> None:
    conn = pg._get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT status, dpo_processed, COUNT(*)
        FROM kart_task_queue
        GROUP BY status, dpo_processed
        ORDER BY status, dpo_processed
    """)
    rows = cur.fetchall()
    cur.close()
    print("\nkart_task_queue DPO status:")
    for status, processed, count in rows:
        flag = "✓" if processed else "○"
        print(f"  {flag} {status}: {count}")

    output_path = Path(os.environ.get(
        "WILLOW_DPO_OUTPUT",
        str(WILLOW_ROOT / "yggdrasil" / "dpo_pairs_kart.jsonl")
    ))
    if output_path.exists():
        lines = sum(1 for _ in open(output_path))
        print(f"\n  {output_path.name}: {lines} pairs")


def main() -> None:
    pg = try_connect()
    if not pg:
        print("[dpo] Cannot connect to Postgres")
        sys.exit(1)

    output_path = Path(os.environ.get(
        "WILLOW_DPO_OUTPUT",
        str(WILLOW_ROOT / "yggdrasil" / "dpo_pairs_kart.jsonl")
    ))
    batch_size = int(os.environ.get("WILLOW_DPO_BATCH", "20"))

    if "--stats" in sys.argv:
        show_stats(pg)
        return

    if "--daemon" in sys.argv:
        interval = int(os.environ.get("WILLOW_DPO_INTERVAL", "60"))
        print(f"[dpo] Daemon started — {os.environ.get('WILLOW_DPO_PROVIDER', 'ollama')} "
              f"(poll every {interval}s)")
        while True:
            try:
                n = process_batch(pg, output_path, batch_size)
                if n:
                    print(f"[dpo] Processed {n} tasks", flush=True)
            except KeyboardInterrupt:
                print("\n[dpo] Stopped")
                break
            except Exception as e:
                print(f"[dpo] Error: {e}", flush=True)
            time.sleep(interval)
    else:
        n = process_batch(pg, output_path, batch_size)
        print(f"[dpo] Done — {n} pairs written to {output_path}")


if __name__ == "__main__":
    main()
