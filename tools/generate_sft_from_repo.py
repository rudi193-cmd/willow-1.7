#!/usr/bin/env python3
# b17: GSR42
"""
generate_sft_from_repo.py — Generate SFT pairs from core repo files via Groq.

Sources: the 6 files that define how the system runs.
Output:  yggdrasil/sft_repo_v1.jsonl
Resumable via sft_repo_v1.state.json
"""

import json, os, re, sys, time
from pathlib import Path

REPO       = Path(__file__).parent.parent
OUTPUT     = REPO / "yggdrasil" / "sft_repo_v1.jsonl"
STATE_FILE = REPO / "yggdrasil" / "sft_repo_v1.state.json"
CREDS_FILE = REPO / "credentials.json"

PAIRS_PER_CHUNK = 8
CHUNK_SIZE      = 2000   # chars per chunk sent to LLM
PACING_S        = 2.2

SOURCES = [
    {
        "id":   "heimdallr-claude-md",
        "path": REPO / ".claude" / "CLAUDE.md",
        "label": "heimdallr/identity",
        "note": "Heimdallr identity, SAP architecture, auth chain, run commands",
    },
    {
        "id":   "hanuman-claude-md",
        "path": Path("/home/sean-campbell/agents/hanuman/CLAUDE.md"),
        "label": "hanuman/identity",
        "note": "Hanuman identity, operating rules, MCP routing, compost hierarchy",
    },
    {
        "id":   "root-claude-md",
        "path": Path("/home/sean-campbell/CLAUDE.md"),
        "label": "system/rules",
        "note": "Top-level operating rules, b17, flat file rule, ΔΣ=42",
    },
    {
        "id":   "willow-store",
        "path": REPO / "core" / "willow_store.py",
        "label": "soil/core",
        "note": "SOIL — SQLite per collection, store.db, WILLOW_STORE_ROOT",
    },
    {
        "id":   "sap-gate",
        "path": REPO / "sap" / "core" / "gate.py",
        "label": "sap/gate",
        "note": "SAP gate — app_id, SAFE manifest, PGP verify, gaps.jsonl, infra IDs",
    },
    {
        "id":   "kart-worker",
        "path": REPO / "kart_worker.py",
        "label": "kart/core",
        "note": "Kart — task queue, bwrap sandbox, execution flow, allow_net",
    },
]

SYSTEM_PROMPT = """You generate training data for Yggdrasil — a small AI assistant that knows how to operate the Willow governed system.

Given a section of source code or documentation, generate exactly {n} factual Q&A pairs that teach Yggdrasil how the system works.

Rules:
- Questions must be concrete and specific (names, paths, constants, procedures, relationships)
- Responses are terse and accurate — 1-4 sentences max, no padding, no apology
- Only state what is directly in the source — never fabricate
- Prefer questions that directly address the BTR failure modes: identity confusion, fabricated system names, invented constants
- Output a JSON array only. No prose. No markdown.

Format: [{{"instruction": "...", "response": "..."}}]"""


def load_api_keys() -> list[str]:
    keys = []
    for var in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"):
        k = os.environ.get(var)
        if k:
            keys.append(k)
    if not keys:
        try:
            creds = json.loads(CREDS_FILE.read_text())
            for var in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"):
                k = creds.get(var)
                if k:
                    keys.append(k)
        except Exception:
            pass
    if not keys:
        sys.exit("No Groq API keys found")
    return keys


def make_client(api_key: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")


def chunk_text(text: str, size: int) -> list[str]:
    """Split on paragraph boundaries, targeting ~size chars per chunk."""
    paragraphs = re.split(r'\n{2,}', text)
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) > size and current:
            chunks.append(current.strip())
            current = p
        else:
            current += "\n\n" + p
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) > 80]


def call_groq(chunk: str, api_key: str, n: int) -> list[dict]:
    client = make_client(api_key)
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(n=n)},
            {"role": "user",   "content": f"Source:\n\n{chunk}"},
        ],
        temperature=0.3,
        max_tokens=1200,
    )
    text = resp.choices[0].message.content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    pairs = json.loads(text)
    if isinstance(pairs, list):
        return [p for p in pairs
                if isinstance(p, dict)
                and p.get("instruction", "").strip()
                and p.get("response", "").strip()]
    return []


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
    keys = load_api_keys()
    print(f"Groq keys: {len(keys)}")

    done = load_state()
    existing = sum(1 for _ in OUTPUT.open()) if OUTPUT.exists() else 0
    print(f"Already done: {len(done)} chunks | Existing pairs: {existing}\n")

    key_idx = 0
    written = existing
    errors  = 0

    with OUTPUT.open("a", encoding="utf-8") as out:
        for source in SOURCES:
            path = source["path"]
            if not path.exists():
                print(f"MISSING: {path}")
                continue

            text = path.read_text(errors="replace")
            chunks = chunk_text(text, CHUNK_SIZE)
            print(f"[{source['id']}] {len(chunks)} chunks — {source['note']}")

            for i, chunk in enumerate(chunks):
                chunk_id = f"{source['id']}:{i}"
                if chunk_id in done:
                    continue

                elapsed = 0.0
                time.sleep(max(0, PACING_S - elapsed))
                t0 = time.time()

                api_key = keys[key_idx % len(keys)]
                key_idx += 1

                try:
                    pairs = call_groq(chunk, api_key, PAIRS_PER_CHUNK)
                    for pair in pairs:
                        record = {
                            "instruction": pair["instruction"].strip(),
                            "response":    pair["response"].strip(),
                            "source":      "repo_sft_v1",
                            "source_type": "repo_doc",
                            "label":       "system_knowledge",
                            "category":    source["label"],
                            "_chunk":      chunk_id,
                        }
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        written += 1

                    done.add(chunk_id)
                    save_state(done)
                    elapsed = time.time() - t0
                    print(f"  [{written}] chunk {i+1}/{len(chunks)} +{len(pairs)} pairs")

                except Exception as e:
                    errors += 1
                    msg = str(e)
                    if "429" in msg:
                        print(f"  429 — rotating key, sleeping 5s")
                        time.sleep(5)
                    else:
                        print(f"  ERR {chunk_id}: {msg[:100]}")
                    if errors > 15:
                        print("Too many errors — stopping.")
                        break

            print()

    print(f"Done. Written: {written}  Errors: {errors}")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
