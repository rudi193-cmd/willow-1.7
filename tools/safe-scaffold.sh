#!/usr/bin/env bash
# safe-scaffold.sh — Create a new SAFE agent folder with manifest + GPG signature
# b17: (assign on first commit)
# ΔΣ=42
#
# Usage:
#   ./tools/safe-scaffold.sh <AgentName> <agent_type> "<description>"
#
# agent_type: professor | worker | operator | system
#
# Examples:
#   ./tools/safe-scaffold.sh Kart worker "Executes queued tasks from LOAM"
#   ./tools/safe-scaffold.sh Oakenscroll professor "Governance and architecture professor"
#
# The script:
#   1. Creates the SAFE folder structure under $WILLOW_SAFE_ROOT
#   2. Generates a b17 ID for the manifest
#   3. Writes safe-app-manifest.json
#   4. Signs it with gpg --detach-sign
#   5. Writes an empty cache/context.json
#
# After running, verify with: ./willow.sh verify

set -euo pipefail

WILLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAFE_ROOT="${WILLOW_SAFE_ROOT:-/media/willow/SAFE/Applications}"

# ── Args ──────────────────────────────────────────────────────────────────────

if [[ $# -lt 3 ]]; then
    echo "Usage: $0 <AgentName> <agent_type> \"<description>\""
    echo "  agent_type: professor | worker | operator | system"
    exit 1
fi

AGENT_NAME="$1"
AGENT_TYPE="$2"
DESCRIPTION="$3"
TODAY="$(date +%Y-%m-%d)"

# Title-case the name (SAFE standard)
AGENT_TITLE="$(echo "${AGENT_NAME:0:1}" | tr '[:lower:]' '[:upper:]')${AGENT_NAME:1}"

AGENT_DIR="${SAFE_ROOT}/${AGENT_TITLE}"

# ── Checks ────────────────────────────────────────────────────────────────────

if [[ ! -d "$SAFE_ROOT" ]]; then
    echo "ERROR: SAFE root not found: $SAFE_ROOT"
    echo "       Set WILLOW_SAFE_ROOT or mount the SAFE drive."
    exit 1
fi

if [[ -d "$AGENT_DIR" ]]; then
    echo "ERROR: SAFE folder already exists: $AGENT_DIR"
    echo "       Delete it first if you want to recreate it."
    exit 1
fi

if ! command -v gpg &>/dev/null; then
    echo "ERROR: gpg not found on PATH"
    echo "       Install gpg: sudo apt install gnupg"
    exit 1
fi

# ── Generate b17 ID ───────────────────────────────────────────────────────────
# Falls back to a random 5-char string from the b17 alphabet if MCP unavailable

ALPHABET="0123456789ACEHKLNRTXZ"
B17=""
for i in {1..5}; do
    idx=$(( RANDOM % 21 ))
    B17="${B17}${ALPHABET:$idx:1}"
done
echo "  b17: ${B17} (random — update with willow_base17 for a canonical ID)"

# ── Create folder structure ───────────────────────────────────────────────────

echo "Creating: ${AGENT_DIR}"
mkdir -p "${AGENT_DIR}"/{bin,cache,index,projects,promote,demote,agents}
touch "${AGENT_DIR}"/{bin,cache,index,projects,promote,demote,agents}/.keep
echo "  Subdirectories: bin cache index projects promote demote agents"

# ── Write manifest ────────────────────────────────────────────────────────────

MANIFEST="${AGENT_DIR}/safe-app-manifest.json"

cat > "$MANIFEST" << EOF
{
  "app_id": "${AGENT_TITLE}",
  "name": "${AGENT_TITLE}",
  "version": "1.0.0",
  "safe_version": ">=2.1.0",
  "b17": "${B17}",
  "description": "${DESCRIPTION}",
  "author": "Sean Campbell",
  "agent_type": "${AGENT_TYPE}",
  "data_streams": [
    {
      "id": "knowledge",
      "purpose": "KB context assembly via SAP",
      "retention": "session"
    }
  ],
  "permissions": [
    "local_llm",
    "cloud_llm_free",
    "willow_kb_read"
  ],
  "privacy_tier": "client_only",
  "local_processing": 1.0
}
EOF
echo "  Manifest: safe-app-manifest.json"

# ── Sign manifest ─────────────────────────────────────────────────────────────

echo "  Signing manifest..."
gpg --detach-sign "${MANIFEST}"
echo "  Signature: safe-app-manifest.json.sig"

# ── Write empty context seed ──────────────────────────────────────────────────

cat > "${AGENT_DIR}/cache/context.json" << EOF
{
  "seeded": "${TODAY}",
  "version": "2.0",
  "format": "b17",
  "b17": []
}
EOF
echo "  Context: cache/context.json (empty — populate with b17 atom IDs)"

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "Done. ${AGENT_TITLE} is now authorized."
echo ""
echo "Next steps:"
echo "  1. Update b17 in manifest: willow_base17 → edit safe-app-manifest.json → re-sign"
echo "  2. Seed context: add atom b17 IDs to cache/context.json"
echo "  3. Verify: ./willow.sh verify"
echo ""
echo "To re-sign after editing the manifest:"
echo "  gpg --detach-sign ${MANIFEST}"
