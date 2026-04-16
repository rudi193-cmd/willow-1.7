# Per-Tool Authorization — Design Spec
b17: PTAD1
ΔΣ=42

**Date:** 2026-04-16
**Status:** Approved

---

## Problem

The SAP authorization gate (`sap/core/gate.py`) is imported in `sap/sap_mcp.py` but never called in the tool dispatcher. All 44 MCP tools are open to any connecting client. Identified in MegaLens security audit 2026-04-16.

---

## Decision

Per-tool authorization. Every tool call must carry an `app_id`. The gate runs on every invocation. Chosen over connection-level auth because professors each get their own stdio process and have different domains/grants — per-tool gives the granularity the multi-professor model requires.

---

## Architecture

Single guard at the top of `call_tool()` in `sap/sap_mcp.py`. All 44 tool schemas get `app_id` added as a required string field. The dispatcher extracts it before any branch, calls `sap_authorized(app_id)`, and returns a structured error payload on denial.

```
call_tool(name, arguments)
  └─ extract app_id → sap_authorized(app_id)
       ├─ denied → return {"error": "unauthorized", "app_id": "...", "tool": name}
       └─ granted → existing if/elif dispatch (unchanged)
```

---

## Components

Three changes, all in `sap/sap_mcp.py`:

### 1. Tool schemas (all 44)
Add to each tool's `inputSchema.properties`:
```json
"app_id": {"type": "string", "description": "SAFE app identifier for authorization"}
```
Add `"app_id"` to each tool's `"required"` array.

### 2. Gate check (line 648, top of `call_tool()` body)
```python
app_id = arguments.get("app_id", "")
if _SAP_GATE and not sap_authorized(app_id):
    return [types.TextContent(type="text", text=json.dumps({
        "error": "unauthorized",
        "app_id": app_id,
        "tool": name,
    }))]
```

### 3. `_SAP_GATE` fallback
No change needed. If the gate failed to import at boot, `_SAP_GATE = False` and the check is bypassed. Existing stderr warning covers this.

---

## Error Handling & Edge Cases

| Scenario | Behavior |
|----------|----------|
| `app_id` missing from arguments | `get("app_id", "")` → empty string → gate denies → unauthorized payload |
| `_SAP_GATE = False` (import failed) | Check bypassed, tools work as before — no regression |
| Valid `app_id`, expired SAFE folder | Gate denies immediately, logs to `gaps.jsonl`, payload returned |
| Authorized caller | Dispatch chain unchanged — no behavior change |

---

## Testing

1. `./willow.sh verify` — confirm all SAFE manifests still pass
2. Tool call without `app_id` → expect `{"error": "unauthorized", ...}`
3. Tool call with valid professor `app_id` → expect normal tool response

---

## Files Changed

- `sap/sap_mcp.py` — only file modified
