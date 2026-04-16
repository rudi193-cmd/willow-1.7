"""
SAP Gate v2 — SAFE folder + PGP manifest verification
b17: 0293H
ΔΣ=42

Authorization chain (all four must pass):
1. SAFE/Applications/<app_id>/ folder exists
2. safe-app-manifest.json present and readable
3. safe-app-manifest.json.sig present
4. gpg --verify confirms signature against Sean's key

Any failure → deny + log to sap/log/gaps.jsonl.
Revocation = delete folder or signature.

Hardened gate for Willow 1.7. Replaces the filesystem-only
gate in Willow 1.5 / Ashokoa/sap/core/gate.py (b17: 36N22).
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

SAFE_ROOT = Path(os.environ.get("WILLOW_SAFE_ROOT", "/media/willow/SAFE/Applications"))
PROFESSOR_ROOT = SAFE_ROOT / "utety-chat" / "professors"
LOG_DIR = Path(__file__).parent.parent / "log"

_EXPECTED_FP = os.environ.get(
    "WILLOW_PGP_FINGERPRINT",
    "96B92D78875F60BE229A0A348F414B8C1B402BB0",
).upper().replace(" ", "")

logger = logging.getLogger("sap.gate")


def _log_gap(app_id: str, reason: str) -> None:
    """Record unauthorized access attempt."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app_id": app_id,
        "event": "access_denied",
        "reason": reason,
    }
    logger.warning("SAP gate denied: app_id=%s reason=%s", app_id, reason)
    log_path = LOG_DIR / "gaps.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _log_grant(app_id: str) -> None:
    """Record authorized access."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app_id": app_id,
        "event": "access_granted",
    }
    log_path = LOG_DIR / "grants.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _verify_pgp(manifest_path: Path) -> tuple[bool, str]:
    """
    Verify the manifest's GPG detached signature AND confirm signer identity.

    Uses gpg --status-fd=1 to get machine-readable output and parse
    the primary key fingerprint from the VALIDSIG status line.
    Expected fingerprint is read from WILLOW_PGP_FINGERPRINT env var.

    Returns (ok, reason).
    """
    sig_path = manifest_path.parent / (manifest_path.name + ".sig")

    if not sig_path.exists():
        return False, f"No signature file: {sig_path.name}"

    try:
        result = subprocess.run(
            ["gpg", "--verify", "--status-fd=1", str(sig_path), str(manifest_path)],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            return False, f"gpg verify failed: {stderr[:200]}"

        stdout = result.stdout.decode("utf-8", errors="replace")
        signer_fp = None
        for line in stdout.splitlines():
            if line.startswith("[GNUPG:] VALIDSIG"):
                parts = line.split()
                # Full line: [GNUPG:] VALIDSIG <subkey-fp> <date> <ts> <ts-exp>
                #            <expire> <reserved> <pk-algo> <hash-algo> <sig-class> <primary-fp>
                # parts indices: 0=[GNUPG:] 1=VALIDSIG 2=subkey-fp ... 11=primary-fp
                if len(parts) >= 12:
                    signer_fp = parts[11].upper()
                    break

        if signer_fp is None:
            excerpt = stdout[:200].replace("\n", " ")
            return False, f"gpg returned success but no VALIDSIG in status output — got: {excerpt}"
        if signer_fp != _EXPECTED_FP:
            return False, f"signature by unexpected key: {signer_fp[:16]}... (expected: {_EXPECTED_FP[:16]}...)"
        return True, "signature verified"

    except FileNotFoundError:
        return False, "gpg not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "gpg verify timed out (5s)"
    except Exception as e:
        return False, f"gpg verify error: {e}"


def authorized(app_id: str) -> bool:
    """
    Four-step authorization check.

    1. SAFE folder exists
    2. Manifest present and readable
    3. Signature file present (checked inside _verify_pgp)
    4. GPG verifies the signature

    Logs all denials. Returns True only when all four pass.
    """
    # Check top-level Applications first, then UTETY/professors/ fallback
    app_path = SAFE_ROOT / app_id
    if not app_path.exists():
        app_path = PROFESSOR_ROOT / app_id

    if not app_path.exists():
        _log_gap(app_id, f"SAFE folder not found: {app_path}")
        return False

    if not app_path.is_dir():
        _log_gap(app_id, f"SAFE path is not a directory: {app_path}")
        return False

    manifest_path = app_path / "safe-app-manifest.json"
    if not manifest_path.exists():
        _log_gap(app_id, f"No manifest at: {manifest_path}")
        return False

    try:
        manifest_path.read_text(encoding="utf-8")
    except Exception as e:
        _log_gap(app_id, f"Manifest unreadable: {e}")
        return False

    sig_ok, sig_reason = _verify_pgp(manifest_path)
    if not sig_ok:
        _log_gap(app_id, f"PGP verification failed: {sig_reason}")
        return False

    _log_grant(app_id)
    return True


def require_authorized(app_id: str) -> None:
    """
    Assert authorization. Raises PermissionError on denial.
    Prefer this over checking authorized() — callers cannot silently ignore it.
    """
    if not authorized(app_id):
        raise PermissionError(
            f"SAP gate denied: '{app_id}' failed authorization. "
            f"Check SAFE folder exists, manifest is present, "
            f"and safe-app-manifest.json.sig is valid."
        )


def get_manifest(app_id: str) -> Optional[dict]:
    """
    Load the safe-app-manifest.json for an authorized app.
    Returns None if not authorized or manifest is malformed.
    Full auth chain runs — including PGP.
    """
    if not authorized(app_id):
        return None

    manifest_path = SAFE_ROOT / app_id / "safe-app-manifest.json"
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception as e:
        logger.error("Manifest parse error for %s: %s", app_id, e)
        return None


def list_authorized() -> list[str]:
    """
    Return all app_ids that pass the full authorization chain.
    Runs gpg --verify for each candidate — use sparingly.
    """
    if not SAFE_ROOT.exists():
        return []

    result = []
    for entry in sorted(SAFE_ROOT.iterdir()):
        if entry.is_dir() and (entry / "safe-app-manifest.json").exists():
            if authorized(entry.name):
                result.append(entry.name)
    return result
