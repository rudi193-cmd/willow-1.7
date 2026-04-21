#!/usr/bin/env bash
# install-mac.sh — Willow macOS Bootstrap
# b17: MAC1  ΔΣ=42
# Community-tested. Run once from Terminal:
#   curl -fsSL https://raw.githubusercontent.com/rudi193-cmd/willow-1.7/master/install-mac.sh | bash

set -e

WILLOW_REPO="https://github.com/rudi193-cmd/willow-1.7"
WILLOW_DIR="/opt/willow-1.7"

ok()   { echo "  [ok] $*"; }
warn() { echo "  [!!] $*"; }
fail() { echo "  [xx] $*"; exit 1; }

echo ""
echo "  Willow — macOS Bootstrap"
echo ""

# ── Homebrew ──────────────────────────────────────────────────────────────────

if ! command -v brew &>/dev/null; then
    warn "Homebrew not found — installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for this session (Apple Silicon / Intel)
    [[ -f /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [[ -f /usr/local/bin/brew   ]] && eval "$(/usr/local/bin/brew shellenv)"
fi
ok "Homebrew: $(brew --version | head -1)"

# ── Dependencies ──────────────────────────────────────────────────────────────

for pkg in python@3.11 postgresql@14 gnupg git; do
    if brew list "$pkg" &>/dev/null; then
        ok "$pkg: already installed"
    else
        warn "Installing $pkg..."
        brew install "$pkg"
    fi
done

# Ensure postgres is on PATH
export PATH="$(brew --prefix postgresql@14)/bin:$PATH"

# ── Clone willow-1.7 ──────────────────────────────────────────────────────────

if [[ -f "$WILLOW_DIR/willow.sh" ]]; then
    ok "willow-1.7 already at $WILLOW_DIR"
else
    warn "Cloning willow-1.7 to $WILLOW_DIR ..."
    sudo git clone "$WILLOW_REPO" "$WILLOW_DIR"
    sudo chown -R "$(whoami)" "$WILLOW_DIR"
    ok "Cloned to $WILLOW_DIR"
fi

# ── Handoff to seed.py ────────────────────────────────────────────────────────

echo ""
echo "  Handing off to seed.py..."
echo ""

exec python3 "$WILLOW_DIR/seed.py"
