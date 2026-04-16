# Per-Tool Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the SAP authorization gate into every MCP tool call — all 49 tools require a valid `app_id` or return `{"error": "unauthorized"}`.

**Architecture:** Single gate check at the top of `call_tool()` in `sap/sap_mcp.py`. `app_id` is injected into all tool schemas via a single post-processing loop in `list_tools()` (DRY — one place, not 49). The gate uses the existing `sap_authorized(app_id)` function which logs denials to `gaps.jsonl` automatically.

**Tech Stack:** Python 3, `mcp` SDK, `sap.core.gate.authorized`, `pytest`, `pytest-asyncio`

> **Note:** The server currently has 49 tools. CLAUDE.md says 44 — it's stale. This plan covers all 49.

---

### Task 1: Write failing tests

**Files:**
- Create: `tests/tools/test_per_tool_auth.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for per-tool authorization gate in sap_mcp.py."""
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _call(name, arguments):
    """Import and invoke call_tool directly."""
    import sap.sap_mcp as mcp_mod
    return await mcp_mod.call_tool(name, arguments)


@pytest.mark.anyio
async def test_missing_app_id_returns_unauthorized():
    """Tool call with no app_id is denied."""
    with patch("sap.sap_mcp.sap_authorized", return_value=False), \
         patch("sap.sap_mcp._SAP_GATE", True):
        result = await _call("store_stats", {})
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["error"] == "unauthorized"
    assert payload["tool"] == "store_stats"


@pytest.mark.anyio
async def test_invalid_app_id_returns_unauthorized():
    """Tool call with an unrecognized app_id is denied."""
    with patch("sap.sap_mcp.sap_authorized", return_value=False), \
         patch("sap.sap_mcp._SAP_GATE", True):
        result = await _call("store_stats", {"app_id": "not-a-real-app"})
    payload = json.loads(result[0].text)
    assert payload["error"] == "unauthorized"
    assert payload["app_id"] == "not-a-real-app"


@pytest.mark.anyio
async def test_valid_app_id_passes_through():
    """Tool call with a valid app_id reaches the dispatcher."""
    with patch("sap.sap_mcp.sap_authorized", return_value=True), \
         patch("sap.sap_mcp._SAP_GATE", True):
        result = await _call("store_stats", {"app_id": "safe-app-utety-chat"})
    payload = json.loads(result[0].text)
    # store_stats returns collection counts — not an auth error
    assert "error" not in payload or payload.get("error") != "unauthorized"


@pytest.mark.anyio
async def test_gate_disabled_passes_through():
    """When _SAP_GATE is False (import failed), tools work without app_id."""
    with patch("sap.sap_mcp._SAP_GATE", False):
        result = await _call("store_stats", {})
    payload = json.loads(result[0].text)
    assert payload.get("error") != "unauthorized"


@pytest.mark.anyio
async def test_all_tools_have_app_id_in_schema():
    """Every tool schema includes app_id as a required field."""
    import sap.sap_mcp as mcp_mod
    tools = await mcp_mod.list_tools()
    for tool in tools:
        props = tool.inputSchema.get("properties", {})
        required = tool.inputSchema.get("required", [])
        assert "app_id" in props, f"{tool.name}: missing app_id in properties"
        assert "app_id" in required, f"{tool.name}: app_id not in required"
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
cd /home/sean-campbell/github/willow-1.7
python -m pytest tests/tools/test_per_tool_auth.py -v 2>&1 | head -40
```

Expected: All 5 tests FAIL (gate check not wired, app_id not in schemas).

---

### Task 2: Inject `app_id` into all tool schemas

**Files:**
- Modify: `sap/sap_mcp.py` — `list_tools()` function (ends at line 641)

- [ ] **Step 1: Add the post-processing loop**

Find the closing of `list_tools()` — the line that reads `]` followed by the closing of the function. Replace:

```python
        ),
    ]
```

with:

```python
        ),
    ]
    # Inject app_id into every tool schema — one place, not 49
    _app_id_field = {"type": "string", "description": "SAFE app identifier for authorization"}
    for _tool in _tools:
        _tool.inputSchema.setdefault("properties", {})["app_id"] = _app_id_field
        if "required" not in _tool.inputSchema:
            _tool.inputSchema["required"] = []
        if "app_id" not in _tool.inputSchema["required"]:
            _tool.inputSchema["required"].append("app_id")
    return _tools
```

And add `_tools = [` at the start of the list (replacing the bare `[`). The full diff is:

Old (line 82):
```python
    return [
        types.Tool(
            name="store_put",
```

New:
```python
    _tools = [
        types.Tool(
            name="store_put",
```

Old (line 641, end of list):
```python
        ),
    ]
```

New:
```python
        ),
    ]
    _app_id_field = {"type": "string", "description": "SAFE app identifier for authorization"}
    for _tool in _tools:
        _tool.inputSchema.setdefault("properties", {})["app_id"] = _app_id_field
        if "required" not in _tool.inputSchema:
            _tool.inputSchema["required"] = []
        if "app_id" not in _tool.inputSchema["required"]:
            _tool.inputSchema["required"].append("app_id")
    return _tools
```

- [ ] **Step 2: Run schema test only**

```bash
cd /home/sean-campbell/github/willow-1.7
python -m pytest tests/tools/test_per_tool_auth.py::test_all_tools_have_app_id_in_schema -v
```

Expected: PASS.

---

### Task 3: Add gate check to `call_tool()`

**Files:**
- Modify: `sap/sap_mcp.py` — `call_tool()` function (line 647)

- [ ] **Step 1: Insert the guard at the top of `call_tool()`**

Old (lines 647–649):
```python
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "store_put":
```

New:
```python
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        app_id = arguments.get("app_id", "")
        if _SAP_GATE and not sap_authorized(app_id):
            return [types.TextContent(type="text", text=json.dumps({
                "error": "unauthorized",
                "app_id": app_id,
                "tool": name,
            }))]

        if name == "store_put":
```

- [ ] **Step 2: Run all auth tests**

```bash
cd /home/sean-campbell/github/willow-1.7
python -m pytest tests/tools/test_per_tool_auth.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 3: Run full test suite to check for regressions**

```bash
cd /home/sean-campbell/github/willow-1.7
python -m pytest tests/ -v
```

Expected: All existing tests still PASS.

---

### Task 4: Commit and restart

- [ ] **Step 1: Commit**

```bash
cd /home/sean-campbell/github/willow-1.7
git add sap/sap_mcp.py tests/tools/test_per_tool_auth.py
git commit -m "feat: wire SAP gate into all 49 MCP tools — per-tool app_id auth

All tool calls now require app_id. Missing or unauthorized app_id
returns {error: unauthorized} payload. Gate check is a single guard
at call_tool() entry. app_id injected into all schemas via post-
processing loop in list_tools().

Closes audit finding: SAP gate imported but never called.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 2: Restart the MCP server**

Call `willow_restart_server` via MCP — Claude Code will reconnect automatically.

- [ ] **Step 3: Smoke test — denied**

Call any tool without `app_id`. Expect:
```json
{"error": "unauthorized", "app_id": "", "tool": "<name>"}
```

- [ ] **Step 4: Smoke test — granted**

Call `willow_status` with `app_id: "safe-app-utety-chat"`. Expect normal status response.

- [ ] **Step 5: Verify gate log**

```bash
tail -5 /home/sean-campbell/github/willow-1.7/sap/log/gaps.jsonl
```

Expected: entries showing the denied smoke test call logged with `event: access_denied`.
