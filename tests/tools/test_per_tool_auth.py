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
    assert payload.get("error") != "unauthorized"


@pytest.mark.anyio
async def test_infra_id_bypasses_gate():
    """ENGINEER/OPERATOR app_ids bypass PGP gate — gate is never called."""
    with patch("sap.sap_mcp.sap_authorized") as mock_auth, \
         patch("sap.sap_mcp._SAP_GATE", True):
        mock_auth.return_value = False  # gate would deny if called
        result = await _call("store_stats", {"app_id": "heimdallr"})
    mock_auth.assert_not_called()
    payload = json.loads(result[0].text)
    assert payload.get("error") != "unauthorized"


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
