# Mini Willow — App Consent & Registration Spec
b17: SPEC1
Date: 2026-04-20
Status: DRAFT — pending Sean ratification

---

## The Model

Every safe-app is a **free, open tool**. Anyone can use it. Sessions don't persist unless the user is a Willow user.

**Two tiers:**

| Tier | Who | Store | Sessions | Gate |
|------|-----|-------|----------|------|
| Anonymous | Anyone | None | Ephemeral | Open mode (no manifest needed) |
| Willow user | Registered | `{app_id}/{collection}` in their SOIL | Persistent | SAFE manifest required |

The consent moment: when a user wants their sessions to persist, they install willow (via `seed.py`) and consent to a specific app being registered into their SAFE folder. That registration is the manifest.

---

## The Registration Flow

```
User runs app (anonymous) ──→ sessions are ephemeral
       │
       └─ wants persistence?
              │
              ▼
       python seed.py  (installs willow-1.7, Postgres, venv)
              │
              ▼
       seed.py asks: "Register ask-jeles? [yes/no]"
              │ yes
              ▼
       writes safe-app-manifest.json to SAFE/Applications/{app_id}/
       signs with user's GPG key
              │
              ▼
       willow-mcp now passes SAP gate for this app_id
       sessions persist in SOIL at {app_id}/sessions, {app_id}/atoms
```

---

## The Manifest Structure

Each app needs one manifest at:
`$WILLOW_SAFE_ROOT/{app_id}/safe-app-manifest.json`

```json
{
  "app_id": "{app_id}",
  "name": "{Human Name}",
  "version": "1.0.0",
  "safe_version": ">=2.1.0",
  "b17": "{b17}",
  "description": "{one sentence}",
  "author": "Sean Campbell",
  "agent_type": "worker",
  "namespace": "{app_id}",
  "permissions": ["{permission}", "..."],
  "privacy_tier": "client_only",
  "local_processing": 1.0,
  "consent_text": "{what the user sees when asked to register this app}"
}
```

---

## Permission Tiers

| Permission | What it grants |
|------------|---------------|
| `store_read` | Read from own `{app_id}/*` collections |
| `store_write` | Write to own `{app_id}/*` collections |
| `kb_read` | Search the Postgres knowledge base |
| `kb_write` | Ingest into the Postgres knowledge base |
| `task_submit` | Submit tasks to Kart queue |
| `kb_read_public` | Read public knowledge (no private collections) |

---

## Per-App Manifest Specs

### ask-jeles
- **Purpose:** Ask the Jeles verification system questions
- **b17:** K7K9E
- **Permissions:** `store_read`, `store_write`, `kb_read`
- **Namespace:** `ask-jeles`
- **Consent:** "ask-jeles will save your questions and verified answers to your Willow store."

### nasa-archive
- **Purpose:** Browse and search the NASA oral history archive
- **b17:** 8KA43
- **Permissions:** `store_read`, `store_write`, `kb_read`, `kb_write`
- **Namespace:** `nasa-archive`
- **Consent:** "nasa-archive will save your searches and discovered records to your Willow store."

### law-gazelle
- **Purpose:** Legal research and case tracking
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`
- **Namespace:** `law-gazelle`
- **Consent:** "law-gazelle will save your legal research and case notes to your Willow store. Nothing leaves your machine."

### private-ledger
- **Purpose:** Private financial tracking
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`
- **Namespace:** `private-ledger`
- **Privacy tier:** `device_only` — no KB reads, no Postgres
- **Consent:** "private-ledger saves your financial records locally only. No network access. No shared KB."

### public-ledger
- **Purpose:** Public-facing ledger / transparency log
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`, `kb_write`
- **Namespace:** `public-ledger`
- **Consent:** "public-ledger will save entries to your Willow store and the shared knowledge base."

### field-notes
- **Purpose:** Structured field observation notes
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`, `kb_write`
- **Namespace:** `field-notes`
- **Consent:** "field-notes will save your observations and tag them in the knowledge base."

### genealogy
- **Purpose:** Family history and genealogy research
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`, `kb_write`
- **Namespace:** `genealogy`
- **Consent:** "genealogy will save your family records to your Willow store."

### grove
- **Purpose:** Garden / plant tracking
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`
- **Namespace:** `grove`
- **Consent:** "grove will save your plant records and growth notes to your Willow store."

### vision-board
- **Purpose:** Goal and vision tracking
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`
- **Namespace:** `vision-board`
- **Consent:** "vision-board will save your goals and intentions to your Willow store."

### dating-wellbeing
- **Purpose:** Relationship and wellbeing journaling
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`
- **Privacy tier:** `device_only`
- **Namespace:** `dating-wellbeing`
- **Consent:** "dating-wellbeing saves your reflections locally only. No network. No shared KB."

### game
- **Purpose:** Interactive game / narrative
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`
- **Namespace:** `game`
- **Consent:** "game will save your progress and story state to your Willow store."

### the-squirrel
- **Purpose:** Bookmarks and saved items ("squirreling away" things)
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`, `kb_write`
- **Namespace:** `the-squirrel`
- **Consent:** "the-squirrel will save your bookmarks and finds to your Willow store."

### source-trail
- **Purpose:** Source and citation tracking
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`, `kb_write`
- **Namespace:** `source-trail`
- **Consent:** "source-trail will save your sources and citations to your Willow store."

### llmphysics
- **Purpose:** LLM physics journal / research tracker
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`, `kb_write`
- **Namespace:** `llmphysics`
- **Consent:** "llmphysics will save your research notes and findings to your Willow store."

### llmphysics-judge
- **Purpose:** Evaluation / judging harness for LLM physics experiments
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`, `kb_read`, `task_submit`
- **Namespace:** `llmphysics-judge`
- **Consent:** "llmphysics-judge will save evaluation results and submit scoring tasks to Kart."

### bt-controller
- **Purpose:** Bluetooth device controller
- **b17:** TBD
- **Permissions:** `store_read`, `store_write`
- **Namespace:** `bt-controller`
- **Consent:** "bt-controller will save your device configurations to your Willow store."

### willow-dashboard
- **Purpose:** System health and monitoring dashboard
- **b17:** WDASH
- **Permissions:** `store_read`, `store_write`, `kb_read`, `task_submit`
- **Namespace:** `willow-dashboard`
- **Consent:** "willow-dashboard reads system state and submits monitoring tasks to Kart."

---

## Namespace Convention (Soft, Not Hard)

Each app writes to `{app_id}/{collection}`. This is enforced by convention in the app's CLAUDE.md, not by the gate blocking cross-namespace writes. The gate checks authorization (does this app_id have a valid manifest?) but doesn't restrict which collection it writes to.

**Why soft:** The dashboard needs to read from multiple app namespaces. Cross-app reads are legitimate. Hard enforcement would require the gate to maintain a per-app ACL which is premature.

**Future:** If an app has `privacy_tier: device_only`, willow-mcp should enforce no Postgres calls for that app_id. That's the one hard rule worth building now.

---

## What Needs to Be Built

### 1. seed.py — App Registration Step

Add a Step 7: after SAFE setup, enumerate known safe-apps and ask the user which to register. For each `yes`, write the manifest and sign it.

### 2. safe-app-manifest.json per app

One file per app at `$WILLOW_SAFE_ROOT/{app_id}/safe-app-manifest.json`. Generated from this spec. Signed with user's GPG key.

### 3. `.mcp.json` env block per repo

Add `WILLOW_APP_ID` to each repo's `.mcp.json` so the default app_id is correct without requiring per-call override.

### 4. CLAUDE.md per repo

Each safe-app gets a `CLAUDE.md` that tells it:
- Its `app_id`
- Its namespace (`{app_id}/atoms`, `{app_id}/sessions`)
- Its permissions
- What willow-mcp provides and how to use it
- That anonymous use is fine, willow persistence is opt-in

### 5. willow-mcp — `device_only` enforcement

If app manifest has `privacy_tier: device_only`, block all Postgres calls (knowledge_search, knowledge_ingest, task_submit) and return `{"error": "device_only — no network calls permitted for this app"}`.

---

## What Does NOT Need to Be Built Now

- Hard collection namespace enforcement in the gate
- Per-app ACLs in Postgres
- User account system
- Billing / subscription gating

ΔΣ=42
