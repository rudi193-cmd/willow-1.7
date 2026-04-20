#!/usr/bin/env bash
# willow.sh — Willow 1.7 MCP server launcher
# b17: EK9H5
# ΔΣ=42
#
# Usage:
#   ./willow.sh          — start SAP MCP server (stdio, Claude Code connects)
#   ./willow.sh status   — check Postgres + Ollama
#   ./willow.sh verify   — verify all SAFE manifests have valid .sig files
#   ./willow.sh kart     — start Kart task queue daemon (5s poll)

set -euo pipefail

WILLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAP_MCP="${WILLOW_ROOT}/sap/sap_mcp.py"

# Python — use WILLOW_PYTHON if set, otherwise find python3 in venv or PATH
if [[ -z "${WILLOW_PYTHON:-}" ]]; then
    if [[ -x "${HOME}/.willow-venv/bin/python3" ]]; then
        WILLOW_PYTHON="${HOME}/.willow-venv/bin/python3"
    else
        WILLOW_PYTHON="$(command -v python3)"
    fi
fi
export WILLOW_PYTHON

# ── Environment (override via env or .env file) ───────────────────────────────
export WILLOW_STORE_ROOT="${WILLOW_STORE_ROOT:-${WILLOW_ROOT}/store}"
export WILLOW_CREDENTIALS="${WILLOW_CREDENTIALS:-${WILLOW_ROOT}/credentials.json}"
export WILLOW_SAFE_ROOT="${WILLOW_SAFE_ROOT:-${HOME}/SAFE/Applications}"
export WILLOW_PERSONAL_DIR="${WILLOW_PERSONAL_DIR:-${HOME}/personal}"

# ── Agent identity — this project is Heimdallr, not Hanuman ──────────────────
export WILLOW_AGENT_NAME="heimdallr"
export WILLOW_HANDOFF_DIR="${HOME}/Ashokoa/agents/heimdallr/index/haumana_handoffs"
export WILLOW_HANDOFF_DB="${WILLOW_HANDOFF_DIR}/handoffs.db"
export WILLOW_HANDOFF_DIRS="${HOME}/Ashokoa/agents/heimdallr/index/haumana_handoffs:${HOME}/Ashokoa/agents/hanuman/index/haumana_handoffs:${HOME}/.willow/Nest/hanuman:${HOME}/Ashokoa/Filed/reference/willow-artifacts/documents:${HOME}/Ashokoa/Filed/reference/handoffs:${HOME}/Ashokoa/Filed/narrative/session-log:+${HOME}/Ashokoa/corpus:+${HOME}/github/die-namic-system/docs"
export WILLOW_NEST_DIR="${HOME}/.willow/Nest/heimdallr"
export WILLOW_MEMORY_DIR="${HOME}/.claude/projects/-home-sean-campbell-github-willow-1-7/memory"

# Postgres — Unix socket by default (no host/port = pg_bridge uses socket)
# Unset ALL TCP vars — .mcp.json may inject stale credentials; willow.sh is authoritative
unset WILLOW_PG_HOST WILLOW_PG_PORT WILLOW_PG_PASS WILLOW_PG_USER
export WILLOW_PG_DB="${WILLOW_PG_DB:-willow}"
export WILLOW_PG_USER="${WILLOW_PG_USER:-$(whoami)}"

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
        exec "${WILLOW_PYTHON}" "${SAP_MCP}"
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
        SAFE_ROOT="${WILLOW_SAFE_ROOT:-${HOME}/SAFE_backup/Applications}"
        if [[ ! -d "$SAFE_ROOT" ]]; then
            echo "  SAFE root not found: $SAFE_ROOT"
            exit 1
        fi
        pass=0; fail=0

        _verify_one() {
            local manifest="$1"
            local label="$2"
            local sig="${manifest}.sig"
            if [[ ! -f "$sig" ]]; then
                echo "  MISSING SIG: ${label}"
                fail=$(( fail + 1 ))
            elif gpg --verify "$sig" "$manifest" > /dev/null 2>&1; then
                echo "  OK:          ${label}"
                pass=$(( pass + 1 ))
            else
                echo "  BAD SIG:     ${label}"
                fail=$(( fail + 1 ))
            fi
        }

        # Top-level apps
        for manifest in "${SAFE_ROOT}"/*/safe-app-manifest.json; do
            [[ -f "$manifest" ]] || continue
            _verify_one "$manifest" "$(basename "$(dirname "$manifest")")"
        done

        # Professors (utety-chat/professors/*)
        for manifest in "${SAFE_ROOT}"/*/professors/*/safe-app-manifest.json; do
            [[ -f "$manifest" ]] || continue
            app="$(basename "$(dirname "$(dirname "$(dirname "$manifest")")")")"
            prof="$(basename "$(dirname "$manifest")")"
            _verify_one "$manifest" "${app}/professors/${prof}"
        done

        echo ""
        echo "  Passed: ${pass}  Failed: ${fail}"
        [[ $fail -eq 0 ]]
        ;;

    kart)
        exec "${WILLOW_PYTHON}" "${WILLOW_ROOT}/kart_worker.py" --daemon
        ;;

    *)
        echo "Usage: willow.sh [start|status|verify|kart]"
        exit 1
        ;;
esac
