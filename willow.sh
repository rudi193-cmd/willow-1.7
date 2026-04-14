#!/usr/bin/env bash
# willow.sh — Willow 1.7 MCP server launcher
# b17: EK9H5
# ΔΣ=42
#
# Usage:
#   ./willow.sh          — start SAP MCP server (stdio, Claude Code connects)
#   ./willow.sh status   — check Postgres + Ollama
#   ./willow.sh verify   — verify all SAFE manifests have valid .sig files

set -euo pipefail

WILLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAP_MCP="${WILLOW_ROOT}/sap/sap_mcp.py"

# ── Environment (override via env or .env file) ───────────────────────────────
export WILLOW_STORE_ROOT="${WILLOW_STORE_ROOT:-${WILLOW_ROOT}/store}"
export WILLOW_CREDENTIALS="${WILLOW_CREDENTIALS:-${WILLOW_ROOT}/credentials.json}"

# Postgres — Unix socket by default (no host/port = pg_bridge uses socket)
# Set WILLOW_PG_HOST to force TCP (escape hatch only)
export WILLOW_PG_DB="${WILLOW_PG_DB:-willow}"
export WILLOW_PG_USER="${WILLOW_PG_USER:-sean}"
# WILLOW_PG_HOST / WILLOW_PG_PORT / WILLOW_PG_PASS: unset = Unix socket

# Load .env if present
if [[ -f "${WILLOW_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${WILLOW_ROOT}/.env"
    set +a
fi

cmd="${1:-start}"

case "$cmd" in
    start|"")
        exec python3 "${SAP_MCP}"
        ;;

    status)
        echo "Willow 1.7 — status check"
        echo "  Store root:  ${WILLOW_STORE_ROOT}"
        echo "  Credentials: ${WILLOW_CREDENTIALS}"
        python3 -c "
import sys; sys.path.insert(0, '${WILLOW_ROOT}/core')
from pg_bridge import try_connect
pg = try_connect()
print('  Postgres:   ', 'connected' if pg else 'not connected')
"
        curl -s --max-time 2 http://localhost:11434/api/tags > /dev/null 2>&1 \
            && echo "  Ollama:      running" \
            || echo "  Ollama:      not running"
        ;;

    verify)
        echo "Willow 1.7 — manifest signature verification"
        SAFE_ROOT="${HOME}/SAFE/Applications"
        if [[ ! -d "$SAFE_ROOT" ]]; then
            echo "  SAFE root not found: $SAFE_ROOT"
            exit 1
        fi
        pass=0; fail=0
        for manifest in "${SAFE_ROOT}"/*/safe-app-manifest.json; do
            app_dir="$(dirname "$manifest")"
            app_name="$(basename "$app_dir")"
            sig="${manifest}.sig"
            if [[ ! -f "$sig" ]]; then
                echo "  MISSING SIG: ${app_name}"
                fail=$(( fail + 1 ))
            elif gpg --verify "$sig" "$manifest" > /dev/null 2>&1; then
                echo "  OK:          ${app_name}"
                pass=$(( pass + 1 ))
            else
                echo "  BAD SIG:     ${app_name}"
                fail=$(( fail + 1 ))
            fi
        done
        echo ""
        echo "  Passed: ${pass}  Failed: ${fail}"
        [[ $fail -eq 0 ]]
        ;;

    *)
        echo "Usage: willow.sh [start|status|verify]"
        exit 1
        ;;
esac
