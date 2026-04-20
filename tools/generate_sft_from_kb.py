#!/usr/bin/env python3
# b17: G7SFT
"""
generate_sft_from_kb.py — Generate SFT pairs from KB atoms via Groq Llama-3.3-70B

Pulls records from SOIL collections, extracts factual content,
generates Q→A pairs in Yggdrasil's voice.
Target: ~500 pairs → yggdrasil/sft_generated_v1.jsonl

Resumable: tracks processed atom IDs in sft_generated_v1.state.json
"""

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).parent.parent
OUTPUT_FILE  = REPO_ROOT / "yggdrasil" / "sft_generated_v1.jsonl"
STATE_FILE   = REPO_ROOT / "yggdrasil" / "sft_generated_v1.state.json"
CREDS_FILE   = REPO_ROOT / "credentials.json"
STORE_ROOT   = Path(os.environ.get("WILLOW_STORE_ROOT", "/home/sean-campbell/.willow/store"))

TARGET_PAIRS = 500
PAIRS_PER_ATOM = 5

# Collections to pull from — richest factual content
SOURCE_COLLECTIONS = [
    "hanuman/atoms",
    "hanuman/projects",
    "hanuman/canon",
    "hanuman/guidance",
    "knowledge/atoms",
    "knowledge/architecture",
    "knowledge/insight",
    "hanuman/gaps",
    "hanuman/rules",
    "hanuman/corrections",
    "hanuman/willow",
    "hanuman/cross-cutting",
    "hanuman/kart",
    "hanuman/feedback",
    "hanuman/shiva",
    "sessions/atoms",
    "knowledge/attribution",
    "knowledge/task-summaries",
    "hanuman/ofshield",
    "hanuman/jeles",
    "hanuman/binder",
    "hanuman/pigeon",
    "hanuman/ada",
    "hanuman/steve",
    "hanuman/gerald",
    "hanuman/nova",
    "utety/faculty",
    "utety/concepts",
    "utety/lore",
    "haumana_handoffs",
    "agents/hanuman",
    "agents/kart",
]

# Skip these atom types — session tracking, not factual knowledge
SKIP_TYPES = {
    "session_narrative", "session_close", "session-start",
    "daily-log", "session-event", "session-work",
}

PROVIDER_BASE  = "https://api.groq.com/openai/v1/chat/completions"
PROVIDER_MODEL = "llama-3.3-70b-versatile"
PACING_S       = 2.2


# ── Credentials ───────────────────────────────────────────────────────

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
        sys.exit("No Groq API keys found in env or credentials.json")
    return keys


def make_client(api_key: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")


def probe_key(api_key: str) -> str | None:
    """Quick probe — returns error message or None if OK."""
    try:
        client = make_client(api_key)
        client.chat.completions.create(
            model=PROVIDER_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        return None
    except Exception as e:
        return str(e)


# ── Store reader ──────────────────────────────────────────────────────

def load_atoms() -> list[dict]:
    atoms = []
    for collection in SOURCE_COLLECTIONS:
        db_path = STORE_ROOT / collection / "store.db"
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            rows = conn.execute("SELECT id, data FROM records").fetchall()
            conn.close()
            for row_id, data_str in rows:
                try:
                    data = json.loads(data_str)
                    data["_store_id"] = row_id
                    data["_collection"] = collection
                    atoms.append(data)
                except Exception:
                    pass
        except Exception as e:
            print(f"  warn: {collection}: {e}")
    return atoms


PII_PATTERNS = [
    # Legal case numbers and medical terms from private cases
    r'\bWC \d{2}-\d+\b',
    r'\b\d{2}-\d{5}-j\d+\b',
    r'System-Induced Pathology',
    r'L5-L6',
    # Home directory usernames → replace with $HOME
    r'/home/[a-zA-Z0-9_-]+/',
]
PII_COMPILED = [re.compile(p) for p in PII_PATTERNS]


def sanitize(text: str) -> str:
    for pat in PII_COMPILED:
        text = pat.sub(lambda m: "$HOME/" if "/home/" in m.group() else "[redacted]", text)
    return text


def is_clean(pair: dict) -> bool:
    combined = pair.get("instruction", "") + " " + pair.get("response", "")
    return not any(pat.search(combined) for pat in PII_COMPILED)


def extract_content(atom: dict) -> str:
    """Pull the most useful text from an atom for Q&A generation."""
    parts = []

    title = atom.get("title", "")
    if title:
        parts.append(f"Title: {title}")

    type_ = atom.get("type", "")
    domain = atom.get("domain", "")
    if type_:
        parts.append(f"Type: {type_}" + (f" | Domain: {domain}" if domain else ""))

    # Prefer rich text fields
    for field in ("summary", "body", "description", "conclusion"):
        val = atom.get(field)
        if val and isinstance(val, str) and len(val) > 20:
            parts.append(f"\n{val[:1500]}")
            break

    # For atoms where content is a file path, try to read it
    content = atom.get("content", "")
    if content and content.startswith("/") and "\n" not in content:
        p = Path(content)
        if p.exists() and p.suffix in (".md", ".txt", ".py", ".json"):
            try:
                text = p.read_text(errors="replace")[:2000]
                if len(text) > 100:
                    parts.append(f"\nFile content preview:\n{text}")
            except Exception:
                pass

    # Structured fields (benchmark results, etc.)
    for field in ("results", "files", "commits", "scripts"):
        val = atom.get(field)
        if val:
            parts.append(f"\n{field}: {json.dumps(val)[:400]}")

    return "\n".join(parts).strip()


# ── LLM caller ───────────────────────────────────────────────────────

SYSTEM_PROMPT = """You generate training data for Yggdrasil — an AI assistant for the Willow governed system.

Given a knowledge atom, generate exactly {n} factual Q&A pairs.

Rules:
- Questions test specific, concrete knowledge (names, paths, procedures, relationships)
- Responses are terse and accurate — no padding, no apology
- Only state what is in the source — never fabricate
- Use Yggdrasil's voice: direct, declarative, points to authoritative source when relevant
- Each response is 1-4 sentences maximum

Output a JSON array only. No prose. No markdown. Format:
[{{"instruction": "...", "response": "..."}}]"""

def call_groq(content: str, api_key: str, n_pairs: int = PAIRS_PER_ATOM) -> list[dict]:
    client = make_client(api_key)
    resp = client.chat.completions.create(
        model=PROVIDER_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(n=n_pairs)},
            {"role": "user", "content": f"Knowledge atom:\n\n{content}"},
        ],
        temperature=0.4,
        max_tokens=1024,
    )
    text = resp.choices[0].message.content.strip()

    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    pairs = json.loads(text)
    if isinstance(pairs, list):
        return [p for p in pairs if isinstance(p, dict) and "instruction" in p and "response" in p]
    return []


# ── State ─────────────────────────────────────────────────────────────

def load_state() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except Exception:
            pass
    return set()


def save_state(processed: set):
    STATE_FILE.write_text(json.dumps(list(processed)))


# ── Main ──────────────────────────────────────────────────────────────

def main():
    keys = load_api_keys()
    print(f"Loaded {len(keys)} Groq key(s) — probing...")
    err = probe_key(keys[0])
    if err:
        print(f"  Key probe failed: {err}")
        sys.exit(1)
    print(f"  Key OK")

    atoms = load_atoms()
    print(f"Loaded {len(atoms):,} atoms from {len(SOURCE_COLLECTIONS)} collections")

    processed = load_state()
    print(f"Already processed: {len(processed)} atoms")

    # Count existing pairs
    existing = 0
    if OUTPUT_FILE.exists():
        existing = sum(1 for _ in OUTPUT_FILE.open())
    print(f"Existing pairs: {existing} / target {TARGET_PAIRS}")

    if existing >= TARGET_PAIRS:
        print("Target already reached.")
        return

    # Filter atoms
    candidates = [
        a for a in atoms
        if a.get("_store_id") not in processed
        and a.get("type", "") not in SKIP_TYPES
        and (a.get("title") or a.get("summary") or a.get("body"))
    ]
    print(f"Candidates after filtering: {len(candidates)}")

    key_idx = 0
    total_written = existing
    errors = 0
    last_call = 0.0

    with OUTPUT_FILE.open("a", encoding="utf-8") as out:
        for atom in candidates:
            if total_written >= TARGET_PAIRS:
                break

            content = extract_content(atom)
            if len(content) < 50:
                continue

            # Rate limiting
            elapsed = time.time() - last_call
            if elapsed < PACING_S:
                time.sleep(PACING_S - elapsed)

            api_key = keys[key_idx % len(keys)]
            key_idx += 1

            atom_id = atom.get("_store_id", "")
            title = atom.get("title", "")[:60]

            try:
                pairs = call_groq(sanitize(content), api_key)
                last_call = time.time()

                for pair in pairs:
                    if total_written >= TARGET_PAIRS:
                        break
                    if not is_clean(pair):
                        continue
                    record = {
                        "instruction": pair["instruction"].strip(),
                        "response":    pair["response"].strip(),
                        "source":      "generated_sft_v1",
                        "source_type": "llm_generated",
                        "label":       "factual_knowledge",
                        "category":    atom.get("_collection", ""),
                        "_atom_id":    atom_id,
                    }
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total_written += 1

                processed.add(atom_id)
                save_state(processed)
                print(f"  [{total_written}/{TARGET_PAIRS}] +{len(pairs)} pairs  {title}")

            except Exception as e:
                last_call = time.time()
                errors += 1
                msg = str(e)
                if "429" in msg:
                    print(f"  429 on key {key_idx % len(keys)} — rotating")
                    time.sleep(5)
                else:
                    print(f"  ERR {title}: {msg[:80]}")
                if errors > 20:
                    print("Too many errors — stopping.")
                    break

    print(f"\nDone. Total pairs: {total_written}  Errors: {errors}")


if __name__ == "__main__":
    main()
