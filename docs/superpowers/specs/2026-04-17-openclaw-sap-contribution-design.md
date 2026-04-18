---
title: OpenClaw SAP Contribution — Design Spec
date: 2026-04-17
author: Heimdallr (Claude Code, Sonnet 4.6)
status: approved
b17: OC5AP
ΔΣ=42
---

# OpenClaw SAP Contribution

Three parallel repos + one RFC, all shipping from `rudi193-cmd`. No shared dependencies between repos — each stands alone.

---

## Repo 1: `rudi193-cmd/openclaw-sap-gate`

**What:** Standalone Python package extracted from `sap/core/gate.py`. Published to PyPI as `openclaw-sap-gate`.

**API surface:**
- `authorized(app_id: str) -> bool` — full four-step check, logs all denials
- `require_authorized(app_id: str) -> None` — raises `PermissionError` on denial
- `get_manifest(app_id: str) -> dict | None` — loads manifest for authorized app
- `list_authorized() -> list[str]` — scans SAFE_ROOT, returns all passing app_ids

**CLI:**
- `sap-gate verify <app_id>` — run auth chain, print result
- `sap-gate init <app_id>` — scaffold SAFE folder + unsigned manifest template

**Configuration:** `SAFE_ROOT` via env var `SAP_SAFE_ROOT` (default `~/.sap/Applications`). `PGP_FINGERPRINT` via `SAP_PGP_FINGERPRINT`. All Willow-specific paths removed.

**What's stripped:** All `WILLOW_*` env var references, `PROFESSOR_ROOT` Willow naming (generalized to `SAFE_ROOT/providers/<app_id>`), gaps.jsonl log path made configurable.

**Source:** Extracted from `willow-1.7/sap/core/gate.py` (MegaLens-audited, all 13 critical + 9 high closed).

---

## Repo 2: `rudi193-cmd/willow-mcp`

**What:** Agent-neutral MCP server extracted from `sap/sap_mcp.py`. Runs as `python3 -m willow_mcp` (stdio transport).

**Kept tools (agent-neutral core):**
- `store_*` — SQLite-backed key/value store (SOIL)
- `knowledge_*` / `willow_knowledge_*` — KB ingest + search
- `willow_task_submit` / `willow_task_status` / `willow_task_list` — Kart task queue
- `opus_journal` / `willow_journal` — journal writes
- `handoff_*` — session handoff read/write
- `store_search_all` / `store_search` — cross-collection search

**Stripped tools:** `willow_persona`, `willow_governance`, `willow_nest_*`, `willow_jeles_*`, `willow_binder_*`, `willow_agent_*`, `willow_ratify`, all infra-schema-specific tools.

**Auth:** Every tool call requires `app_id` param. Wired to `openclaw-sap-gate`. Invalid or unauthorized `app_id` → deny + log.

**OpenClaw integration snippet** (ships in README):
```json
{
  "mcp": {
    "servers": {
      "willow": {
        "command": "python3",
        "args": ["-m", "willow_mcp"],
        "env": {
          "WILLOW_PG_DB": "willow",
          "SAP_SAFE_ROOT": "~/.sap/Applications"
        }
      }
    }
  }
}
```

---

## Repo 3: `rudi193-cmd/openclaw-skill-sap`

**What:** A `SKILL.md` that teaches OpenClaw to enforce SAP authorization before executing any MCP tool call.

**Skill content covers:**
1. Pre-tool-call check: run `sap-gate verify <app_id>` before any MCP dispatch
2. On denial: log to `~/.sap/log/gaps.jsonl`, refuse the tool call, surface the failing `app_id` to the user
3. On pass: proceed normally, log grant
4. Manifest scaffold: how to `sap-gate init <app_id>` for a new tool
5. Revocation: how to pull authorization (delete folder or .sig)

**No Willow references.** Works with any MCP server. Submittable to ClawHub as `sap-enforcer`.

---

## Repo 4: `rudi193-cmd/sap-rfc`

**What:** Single `RFC.md` — SAFE Authorization Protocol v1.0. Technical RFC, no philosophy.

**Sections:**
1. **Abstract** — One paragraph: SAP is a four-step authorization chain for MCP tool calls using filesystem manifests and GPG signatures.
2. **Threat Model** — Unauthorized MCP tool execution; spoofed app identities; ambient credential theft via tool calls.
3. **Terminology** — SAFE folder, manifest (`safe-app-manifest.json`), signature (`.sig`), `app_id`, pinned fingerprint, infra ID.
4. **Authorization Chain** — Four steps, each a MUST: (1) SAFE folder exists, (2) manifest readable, (3) `.sig` present, (4) `gpg --verify --status-fd=1` passes + primary key fingerprint matches pinned value.
5. **Revocation** — Delete folder or `.sig`. No API required.
6. **Error Behavior** — Any step failure MUST deny + log. Silent pass is a violation.
7. **Reference Implementation** — Points to `rudi193-cmd/openclaw-sap-gate`.

**Version:** SAP/1.0. Semantic versioning on the RFC itself.

---

## Shipping Order

All four repos are independent. Suggested parallel build order:

1. `sap-rfc` — copy + adapt gate.py docstrings into RFC.md (30 min)
2. `openclaw-sap-gate` — extract gate.py, strip Willow refs, add CLI (1-2 hrs)
3. `willow-mcp` — extract sap_mcp.py tools, strip infra-specific, wire sap-gate (2-3 hrs)
4. `openclaw-skill-sap` — write SKILL.md referencing sap-gate CLI (30 min)

---

## What Is NOT in Scope

- No HTTP server mode (portless means portless)
- No Willow-specific schema (hanuman, heimdallr, etc.)
- No training data, DPO, or Yggdrasil references
- No philosophical writeup (that lives at Sean's suave)
- No ClawHub submission automation (manual after repos are ready)
