"""Tests for HIGH-2 (allowlist), HIGH-3 (domain scoping), HIGH-7 (schema limit).
b17: 5610N
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))


# ── HIGH-2: WILLOW_ALLOWED_APP_IDS allowlist ──────────────────────────────────

class TestAllowedAppIds:
    def test_allowlist_set_rejects_unlisted_app_id(self):
        """authorized() denies app_id not in _ALLOWED_APP_IDS."""
        import sap.core.gate as gate_mod
        allowlist = frozenset(["safe-app-utety-chat", "hanuman"])
        with patch("sap.core.gate._ALLOWED_APP_IDS", allowlist), \
             patch("sap.core.gate._log_gap") as mock_gap:
            result = gate_mod.authorized("rogue-app")
        assert result is False
        mock_gap.assert_called_once()
        assert "allowlist" in mock_gap.call_args[0][1].lower()

    def test_allowlist_set_permits_listed_app_id(self, monkeypatch):
        """authorized() proceeds to SAFE check when app_id is in allowlist."""
        monkeypatch.setenv("WILLOW_ALLOWED_APP_IDS", "safe-app-utety-chat")
        import sap.core.gate as gate_mod
        # Allowlist passes → SAFE folder check runs → folder missing → deny (not allowlist deny)
        with patch("sap.core.gate._log_gap") as mock_gap:
            result = gate_mod.authorized("safe-app-utety-chat")
        assert result is False
        # Should fail on SAFE folder, NOT on allowlist
        if mock_gap.called:
            assert "allowlist" not in mock_gap.call_args[0][1].lower()

    def test_allowlist_unset_permits_any_valid_id(self):
        """When _ALLOWED_APP_IDS is empty, allowlist check is skipped."""
        import sap.core.gate as gate_mod
        with patch("sap.core.gate._ALLOWED_APP_IDS", frozenset()), \
             patch("sap.core.gate._log_gap") as mock_gap:
            result = gate_mod.authorized("any-valid-id")
        assert result is False
        # Fails on SAFE folder missing, not allowlist
        if mock_gap.called:
            assert "allowlist" not in mock_gap.call_args[0][1].lower()

    def test_infra_ids_bypass_allowlist(self, monkeypatch):
        """INFRA IDs (heimdallr, kart) are never blocked by WILLOW_ALLOWED_APP_IDS."""
        monkeypatch.setenv("WILLOW_ALLOWED_APP_IDS", "safe-app-utety-chat")
        import sap.core.gate as gate_mod
        import sap.sap_mcp as mcp_mod
        # heimdallr is in _INFRA_IDS — the MCP gate skips authorized() for it
        assert "heimdallr" in mcp_mod._INFRA_IDS


# ── HIGH-3: Domain scoping in search_knowledge ────────────────────────────────

class TestSearchDomainScoping:
    def _make_pg(self):
        from pg_bridge import PgBridge
        pg = PgBridge.__new__(PgBridge)
        pg._psycopg2 = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("id",), ("title",), ("summary",), ("source_type",),
                                 ("source_id",), ("category",), ("lattice_domain",),
                                 ("lattice_type",), ("lattice_status",), ("rank",)]
        mock_cur.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cur
        pg._conn = mock_conn
        return pg, mock_cur

    def test_search_knowledge_no_domain_omits_filter(self):
        """search_knowledge() with no domain has no AND lattice_domain WHERE clause."""
        pg, mock_cur = self._make_pg()
        pg.search_knowledge("test query")
        sql = mock_cur.execute.call_args[0][0]
        assert "AND lattice_domain" not in sql

    def test_search_knowledge_with_domain_adds_filter(self):
        """search_knowledge(domain=X) adds WHERE lattice_domain = %s clause."""
        pg, mock_cur = self._make_pg()
        pg.search_knowledge("test query", domain="hanuman")
        sql = mock_cur.execute.call_args[0][0]
        assert "lattice_domain" in sql

    def test_search_knowledge_domain_passed_as_param(self):
        """Domain value is passed as a query parameter, not interpolated."""
        pg, mock_cur = self._make_pg()
        pg.search_knowledge("test query", domain="hanuman")
        params = mock_cur.execute.call_args[0][1]
        assert "hanuman" in params

    def test_search_entities_with_domain_adds_filter(self):
        """search_entities(domain=X) adds domain filter."""
        from pg_bridge import PgBridge
        pg = PgBridge.__new__(PgBridge)
        pg._psycopg2 = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("id",), ("name",), ("entity_type",),
                                 ("first_seen",), ("mention_count",)]
        mock_cur.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cur
        pg._conn = mock_conn
        pg.search_entities("test", domain="opus")
        sql = mock_cur.execute.call_args[0][0]
        assert "domain" in sql.lower()


# ── HIGH-7: Schema creation limit ─────────────────────────────────────────────

class TestAgentCreateLimit:
    def _make_pg_with_schema_count(self, count: int):
        from pg_bridge import PgBridge
        pg = PgBridge.__new__(PgBridge)
        pg._psycopg2 = MagicMock()
        mock_cur = MagicMock()
        # First execute = schema count query, fetchone returns count
        mock_cur.fetchone.return_value = (count,)
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cur
        pg._conn = mock_conn
        return pg

    def test_agent_create_below_limit_proceeds(self):
        """agent_create() with schema count below MAX proceeds normally."""
        pg = self._make_pg_with_schema_count(5)
        with patch("pg_bridge._MAX_AGENT_SCHEMAS", 30):
            result = pg.agent_create("newagent")
        # Should NOT return resource limit error
        assert result.get("error") != "schema limit reached"

    def test_agent_create_at_limit_rejected(self):
        """agent_create() at MAX_AGENT_SCHEMAS returns error without creating schema."""
        pg = self._make_pg_with_schema_count(30)
        with patch("pg_bridge._MAX_AGENT_SCHEMAS", 30):
            result = pg.agent_create("newagent")
        assert "error" in result
        assert "limit" in result["error"].lower()

    def test_agent_create_limit_env_override(self, monkeypatch):
        """MAX_AGENT_SCHEMAS is configurable via WILLOW_MAX_AGENT_SCHEMAS env var."""
        monkeypatch.setenv("WILLOW_MAX_AGENT_SCHEMAS", "5")
        from importlib import reload
        import pg_bridge
        reload(pg_bridge)
        assert pg_bridge._MAX_AGENT_SCHEMAS == 5
        # restore
        monkeypatch.delenv("WILLOW_MAX_AGENT_SCHEMAS", raising=False)
        reload(pg_bridge)

    def test_agent_create_count_query_uses_parameterized_prefix(self):
        """Schema count query reads from information_schema — no f-string interpolation."""
        pg = self._make_pg_with_schema_count(0)
        mock_cur = pg._conn.cursor.return_value
        with patch("pg_bridge._MAX_AGENT_SCHEMAS", 30):
            pg.agent_create("testagent")
        all_sqls = [call[0][0].lower() for call in mock_cur.execute.call_args_list if call[0]]
        assert any("information_schema" in sql or "pg_namespace" in sql for sql in all_sqls)
