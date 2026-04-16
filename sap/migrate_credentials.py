#!/usr/bin/env python3
"""
Migrate credentials from willow-1.4 Fernet vault → willow-1.7 credentials.json.
Run once. Safe to re-run (merges, does not overwrite non-empty values).
"""
import json, sys
from pathlib import Path

VAULT_ROOT   = Path.home() / "github" / "willow-1.4"
CREDS_OUT    = Path(__file__).parent.parent / "credentials.json"
KEYS_WANTED  = [
    "GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3",
    "CEREBRAS_API_KEY", "CEREBRAS_API_KEY_2", "CEREBRAS_API_KEY_3",
    "SAMBANOVA_API_KEY", "SAMBANOVA_API_KEY_2", "SAMBANOVA_API_KEY_3",
]

sys.path.insert(0, str(VAULT_ROOT))
try:
    from core.credentials import get_cred
except ImportError as e:
    print(f"Cannot import willow-1.4 credentials: {e}")
    sys.exit(1)

existing = json.loads(CREDS_OUT.read_text()) if CREDS_OUT.exists() else {}
migrated = 0
skipped  = 0

for key in KEYS_WANTED:
    if existing.get(key):          # already filled — don't overwrite
        skipped += 1
        continue
    val = get_cred(key)
    if val:
        existing[key] = val
        migrated += 1
        print(f"  + {key}")
    else:
        print(f"  - {key} (not in vault)")

CREDS_OUT.write_text(json.dumps(existing, indent=2) + "\n")
print(f"\nDone — {migrated} migrated, {skipped} already present.")
print(f"Output: {CREDS_OUT}")
