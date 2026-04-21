#!/usr/bin/env python3
"""migrate_credentials.py — move credentials.json into the Fernet vault.
b17: CRED1  ΔΣ=42

Run once. Reads credentials.json, writes every key to ~/.willow_creds.db,
then archives the plaintext file to ~/SAFE/credentials.json.migrated.
"""
import json
import shutil
import sqlite3
import sys
from pathlib import Path

CREDS_FILE  = Path(__file__).parent.parent / "credentials.json"
KEY_PATH    = Path.home() / ".willow_master.key"
VAULT_PATH  = Path.home() / ".willow_creds.db"
ARCHIVE_DIR = Path.home() / "SAFE"


def vault_init():
    from cryptography.fernet import Fernet
    if not KEY_PATH.exists():
        key = Fernet.generate_key()
        KEY_PATH.write_bytes(key)
        KEY_PATH.chmod(0o600)
        print(f"  ✓  Master key created: {KEY_PATH}")
    else:
        print(f"  ✓  Master key exists: {KEY_PATH}")
    conn = sqlite3.connect(str(VAULT_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS credentials
        (name TEXT PRIMARY KEY, env_key TEXT, value_enc BLOB)""")
    conn.commit()
    conn.close()
    print(f"  ✓  Vault ready: {VAULT_PATH}")


def vault_write(name: str, value: str):
    from cryptography.fernet import Fernet
    f   = Fernet(KEY_PATH.read_bytes().strip())
    enc = f.encrypt(value.encode())
    conn = sqlite3.connect(str(VAULT_PATH))
    conn.execute(
        "INSERT OR REPLACE INTO credentials (name, env_key, value_enc) VALUES (?,?,?)",
        (name, name, enc),
    )
    conn.commit()
    conn.close()


def vault_count() -> int:
    conn = sqlite3.connect(str(VAULT_PATH))
    n = conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0]
    conn.close()
    return n


def main():
    print()
    print("  credentials.json → vault migration")
    print("  ───────────────────────────────────")

    if not CREDS_FILE.exists():
        print(f"  ✗  Not found: {CREDS_FILE}")
        sys.exit(1)

    try:
        creds = json.loads(CREDS_FILE.read_text())
    except Exception as e:
        print(f"  ✗  Could not read credentials.json: {e}")
        sys.exit(1)

    try:
        vault_init()
    except ImportError:
        print("  ✗  cryptography not installed — run: pip install cryptography")
        sys.exit(1)

    skipped = []
    migrated = []

    for name, value in creds.items():
        if not value or "PASTE_YOUR" in str(value):
            skipped.append(name)
            continue
        vault_write(name, str(value))
        migrated.append(name)
        print(f"  ✓  {name}")

    if skipped:
        print()
        for name in skipped:
            print(f"  —  skipped (placeholder): {name}")

    print()
    print(f"  Migrated: {len(migrated)}   Skipped: {len(skipped)}")
    print(f"  Vault total: {vault_count()} credentials")

    # Archive credentials.json
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / "credentials.json.migrated"
    shutil.move(str(CREDS_FILE), str(archive_path))
    print()
    print(f"  ✓  Archived to: {archive_path}")
    print(f"  ✓  credentials.json removed from repo")
    print()
    print("  Done. Your keys are in the vault.")
    print("  The plaintext file is gone from the repo.")
    print()


if __name__ == "__main__":
    main()
