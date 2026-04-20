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

The manifest already lives in each repo at `safe-app-manifest.json`. Registration = copying it to the SAFE folder and signing it with the user's GPG key.

---

## Permission Tiers (Willow-mcp mapping)

| App permission | willow-mcp tools granted |
|----------------|--------------------------|
| `store_read` | `store_get`, `store_list`, `store_search` |
| `store_write` | `store_put`, `store_update` |
| `knowledge:read` / `willow_kb_read` | `knowledge_search` |
| `knowledge:write` / `willow_kb_write` | `knowledge_ingest` |
| `task_submit` | `task_submit`, `task_status`, `task_list` |

Apps with `privacy_tier: client_only` and no cloud permissions: block `knowledge_ingest` and `task_submit`.
Apps with `privacy_tier: public`: allow `knowledge_search` only.

---

## Per-App Manifest Registry

Source of truth: `safe-app-manifest.json` in each repo. Descriptions and b17s from those files.

| app_id | name | b17 | description | privacy_tier | willow_store_namespace |
|--------|------|-----|-------------|--------------|----------------------|
| `ask-jeles` | AskJeles | L5509 | AI librarian — verified web search (Smithsonian, LoC, NASA, NIH). No SEO slop. Deposits findings to local Binder. | mixed | `ask-jeles` |
| `nasa-archive` | NASA Archive Explorer | 247KA | Explore and download NASA open datasets — imagery, mission telemetry, earth science — with a local pipeline for private analysis. | client_only | `nasa-archive` |
| `safe-app-law-gazelle` | law-gazelle | E472A | Legal reference tool — statute search, case summaries, plain-language explainers from verified sources. | client_only | `law-gazelle` |
| `safe-app-private-ledger` | private-ledger | H7864 | Local personal budgeting companion — fully private, no cloud sync, paired with Public Ledger. | client_only | `private-ledger` |
| `safe-app-public-ledger` | public-ledger | C86E9 | Public records financial auditor — search government budgets and IRS Form 990 filings for nonprofits. | client_only | `public-ledger` |
| `safe-app-field-notes` | field-notes | H9EL2 | Quick-capture notebook for observations, ideas, and research notes. Feeds into The Binder. | client_only | `field-notes` |
| `safe-app-genealogy` | genealogy | EC768 | The Aionic Genealogy Project — family tree research with FamilySearch API, Find a Grave, and Paperclip DB cross-reference. | client_only | `genealogy` |
| `grove` | Grove | L8671 | Sovereign workspace messaging where every conversation grows into knowledge. | client_only | `grove` |
| `vision-board` | Vision Board | TBD | Surfaces patterns in what users are already reaching toward — connects to photo libraries, categorizes with client-side AI. The app is a lens, not a warehouse. | client_only | `vision-board` |
| `dating-wellbeing` | Dating Wellbeing Analyzer | 2NCAL | Privacy-first dating profile analysis with red flag detection and pattern learning. | client_only | `dating-wellbeing` |
| `safe-app-game` | game (Jane GM) | 742CA | Universal game master for TTRPGs, board games, and co-op play. Jane in your pocket. | client_only | `game` |
| `safe-app-the-squirrel` | The Squirrel | NNA92 | Genealogy research terminal — collect fragments, build the tree, find what's misfiled. Jeles works the desk. The Binder works the back. | mixed | `the-squirrel` |
| `safe-app-source-trail` | source-trail | K7NA1 | Citation and source tracker — log, verify, and link your research sources. AskJeles companion. | client_only | `source-trail` |
| `safe-app-llmphysics` | LLMPhysics Judge | TBD | r/LLMPhysics Competition Paper Judge — scores submitted physics papers against the official competition rubric (100 pts). Browser-based, bring your own API key. | public | `llmphysics` |
| `safe-app-llmphysics-bot` | llmphysics-bot | 6HANC | Reddit bot for r/LLMPhysics — responds to !define commands with Wikipedia physics summaries. | public | `llmphysics-bot` |
| `utety-chat` | UTETY Chat | 98LAL | Chat with UTETY professors — privacy-first conversational AI with 18 faculty personas. | client_only | `utety-chat` |
| `safe-app-UTETY-Reddit-Bots` | UTETY Reddit Bots | 6HANC | Reddit bots for UTETY University faculty. Each bot is a Devvit app installed per-subreddit. | public | `utety-bots` |
| `bt-controller` | BT Controller | 9E0H3 | Web Bluetooth device manager — bypass Windows BT stack. Data local only. No cloud. | device_only | `bt-controller` |
| `willow-dashboard` | Willow Dashboard | WDASH | System health and monitoring TUI — Heimdallr chat, Kart queue, knowledge stats, Yggdrasil status. | client_only | `willow-dashboard` |

---

## Issues Found in Existing Manifests

1. **`safe-app-llmphysics`** — manifest is `safe-app-manifest.js` (not `.json`). No valid JSON manifest. Needs to be converted.
2. **`safe-app-the-squirrel`** — `app_id` is `safe-app-the-squirrel` in repo manifest but SAFE folder uses `the-squirrel`. These need to be consistent.
3. **`safe-app-genealogy`** — shares legacy b17 `EC768` with `the-squirrel`. Collision — one needs a new b17.
4. **`bt-controller`** — manifest uses `slug` not `app_id`. Needs SAP-format update.
5. **`safe-app-UTETY-Reddit-Bots`** and **`safe-app-llmphysics-bot`** — share the same b17 `6HANC`. Collision.
6. **`vision-board`** — no `safe-app-manifest.json` found. Needs one created.
7. Most manifests have `app_id` prefixed with `safe-app-` but SAFE folder uses short names. Need a convention decision: use short names everywhere.

---

## Convention Decision (needs ratification)

**Recommendation:** `app_id` = short name without `safe-app-` prefix.

| Repo | Current app_id | Recommended app_id |
|------|---------------|-------------------|
| safe-app-the-squirrel | `safe-app-the-squirrel` | `the-squirrel` |
| safe-app-genealogy | `safe-app-genealogy` | `genealogy` |
| safe-app-field-notes | `safe-app-field-notes` | `field-notes` |
| safe-app-source-trail | `safe-app-source-trail` | `source-trail` |
| safe-app-public-ledger | `safe-app-public-ledger` | `public-ledger` |
| safe-app-private-ledger | `safe-app-private-ledger` | `private-ledger` |
| safe-app-law-gazelle | `safe-app-law-gazelle` | `law-gazelle` |
| safe-app-game | `safe-app-game` | `game` |
| safe-app-llmphysics-bot | `safe-app-llmphysics-bot` | `llmphysics-bot` |
| safe-app-UTETY-Reddit-Bots | `safe-app-UTETY-Reddit-Bots` | `utety-bots` |

Already correct: `ask-jeles`, `nasa-archive`, `grove`, `dating-wellbeing`, `utety-chat`, `bt-controller`.

---

## Namespace Convention (Soft)

Each app writes to `{app_id}/{collection}`. Enforced by convention in CLAUDE.md, not by hard gate blocking. Gate checks authorization (valid manifest?) not collection scope.

**Exception — `device_only` apps** (`bt-controller`, `dating-wellbeing`): willow-mcp blocks all Postgres calls. Store-only, no KB, no Kart.

---

## What Needs to Be Built

1. **seed.py Step 7** — app registration loop: enumerate known safe-apps, ask user to consent per app, write manifest to SAFE folder, sign with GPG
2. **Fix manifest issues** listed above (llmphysics .js→.json, app_id normalization, b17 collisions, vision-board missing manifest)
3. **`WILLOW_APP_ID`** env in each repo's `.mcp.json`
4. **`CLAUDE.md`** per repo — identity, namespace, permissions, willow-mcp usage
5. **`device_only` enforcement** in willow-mcp — block Postgres calls for flagged apps

## What Does NOT Need to Be Built Now

- Hard collection namespace enforcement in the gate
- Per-app ACLs in Postgres
- User account system / billing

ΔΣ=42
