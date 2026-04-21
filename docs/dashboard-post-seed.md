# Dashboard Launch — Post-Seed Integration
b17: EK9H5  ΔΣ=42

After the Willow seed installs and the system is initialized, launch the
terminal dashboard via:

```bash
./willow.sh dashboard
```

This inherits the full Willow environment (WILLOW_STORE_ROOT, WILLOW_SAFE_ROOT,
WILLOW_PG_DB, agent identity, etc.) and hands off to willow-dashboard.sh.

---

## What happens at first launch

1. Boot screen — environment probe (Postgres, Ollama, SAFE, SOIL, MCP, GPG)
2. New user onboarding (if no boot config exists):
   - Heimdallr welcome + data covenant
   - MIT + §1.1 legal acknowledgement
   - Path selection (Professional / Casual / New Here)
   - GPG key creation — sets WILLOW_PGP_FINGERPRINT
3. Dashboard loads with configured agent and card set

## Subsequent launches

1. Environment probe
2. GPG authentication (passphrase or agent)
3. Dashboard — resumes last session state

---

## Dashboard location

The dashboard is a separate repo. Install alongside willow-1.7:

```bash
git clone https://github.com/rudi193-cmd/willow-dashboard \
          $(dirname $WILLOW_ROOT)/willow-dashboard
```

`./willow.sh dashboard` searches for it in:
- `../willow-dashboard` (sibling, preferred)
- `~/github/willow-dashboard`
- `~/willow-dashboard`

---

## Seed integration point

When the seed completes provisioning, call the dashboard as the final step:

```bash
# At the end of seed install / provisioning script:
echo ""
echo "Willow installed. Launching dashboard..."
sleep 1
"${WILLOW_ROOT}/willow.sh" dashboard
```

The dashboard's boot sequence handles first-run detection automatically —
no additional seed-side configuration needed.

---

## Flags

| Flag | Effect |
|------|--------|
| `./willow.sh dashboard` | Normal launch — boot + dashboard |
| `./willow.sh dashboard --dev` | Skip boot (dev / debug) |
| `./willow.sh dashboard --setup` | Force re-run onboarding |
| `./willow.sh dashboard --agent=gerald` | Run as a specific agent |

---

## Version

willow-dashboard v0.2.0 — card system, boot/auth, session persistence,
graceful shutdown via agent.
