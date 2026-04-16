# tools/ — Willow 1.7 Admin Scripts
<!-- b17: (assign on commit) · ΔΣ=42 -->

Utility scripts for setup, maintenance, and SAFE management.

```
tools/
└── safe-scaffold.sh   # Create a new SAFE agent folder with manifest + GPG signature
```

---

## safe-scaffold.sh

Creates a new authorized agent in one step: folder structure, manifest, GPG signature,
and empty context seed.

```bash
./tools/safe-scaffold.sh <AgentName> <agent_type> "<description>"
```

**agent_type:** `professor` | `worker` | `operator` | `system`

**Examples:**
```bash
# New task worker
./tools/safe-scaffold.sh MyWorker worker "Handles file ingestion tasks"

# New professor
./tools/safe-scaffold.sh Ganesha professor "Mathematics and systems architecture"
```

**What it creates:**
```
$WILLOW_SAFE_ROOT/MyWorker/
├── safe-app-manifest.json       ← manifest with generated b17
├── safe-app-manifest.json.sig   ← GPG detached signature
├── bin/.keep
├── cache/
│   ├── .keep
│   └── context.json             ← empty b17 seed
├── index/.keep
├── projects/.keep
├── promote/.keep
├── demote/.keep
└── agents/.keep
```

**After scaffolding:**
1. Replace the random b17 in the manifest with a canonical one from `willow_base17`
2. Re-sign: `gpg --detach-sign $WILLOW_SAFE_ROOT/MyWorker/safe-app-manifest.json`
3. Seed context: add atom b17 IDs to `cache/context.json`
4. Verify: `./willow.sh verify`

**Requirements:** `gpg` on PATH with Sean's signing key in the keyring.

---

See `docs/SAFE_FOLDER_STANDARD.md` in the SAFE repo for the full authorization spec.
