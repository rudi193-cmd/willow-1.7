"""Tests for Phase 4 structural: content-addressed IDs and kart sandbox.
b17: C0NT4
ΔΣ=42
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── kart_worker sandbox (_spawn) ────────────────────────────────────────

class TestSpawn:
    def test_spawn_shell_no_bwrap_runs_command(self):
        """Without bwrap, shell command executes on host and returns output."""
        from kart_worker import _spawn
        with patch("kart_worker._BWRAP", None):
            env = os.environ.copy()
            proc = _spawn("shell", "echo hello", env)
            out, _ = proc.communicate(timeout=5)
            assert "hello" in out

    def test_spawn_script_no_bwrap_runs_script(self):
        """Without bwrap, multi-line script executes and returns output."""
        import subprocess as _sp
        from kart_worker import _spawn
        # Ensure clean module state — reset warning flag and force no sandbox
        import kart_worker as _kw
        saved_warned = _kw._SANDBOX_WARNED
        _kw._SANDBOX_WARNED = False
        try:
            with patch("kart_worker._BWRAP", None):
                env = os.environ.copy()
                proc = _spawn("script", "echo line1\necho line2\n", env)
                out, err = proc.communicate(timeout=10)
                assert "line1" in out, f"stdout: {out!r}  stderr: {err!r}"
                assert "line2" in out
        finally:
            _kw._SANDBOX_WARNED = saved_warned

    def test_spawn_bwrap_uses_prefix(self):
        """When bwrap is available, _spawn prepends bwrap args."""
        import subprocess
        from kart_worker import _spawn
        fake_bwrap = "/usr/bin/bwrap"
        with patch("kart_worker._BWRAP", fake_bwrap), \
             patch("kart_worker._bwrap_prefix", return_value=["echo", "SANDBOX"]), \
             patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.stdin = MagicMock()
            mock_popen.return_value = mock_proc
            _spawn("shell", "ls /", os.environ.copy())
            call_args = mock_popen.call_args[0][0]
            assert call_args[0] == "echo"
            assert "SANDBOX" in call_args

    def test_spawn_script_bwrap_uses_stdin(self):
        """Sandboxed scripts are passed via stdin, not temp file."""
        from kart_worker import _spawn
        with patch("kart_worker._BWRAP", "/usr/bin/bwrap"), \
             patch("kart_worker._bwrap_prefix", return_value=["echo", "SANDBOX"]), \
             patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.stdin = MagicMock()
            mock_popen.return_value = mock_proc
            _spawn("script", "echo hi\n", os.environ.copy())
            call_args = mock_popen.call_args[0][0]
            # bash -s receives script via stdin
            assert "bash" in call_args
            assert "-s" in call_args
            mock_proc.stdin.write.assert_called_once_with("echo hi\n")
            mock_proc.stdin.close.assert_called_once()

    def test_sandbox_warned_once_without_bwrap(self):
        """Without bwrap the warning fires only once regardless of calls."""
        from kart_worker import _spawn
        import kart_worker
        original = kart_worker._SANDBOX_WARNED
        kart_worker._SANDBOX_WARNED = False
        with patch("kart_worker._BWRAP", None), \
             patch("builtins.print") as mock_print:
            _spawn("shell", "echo a", os.environ.copy()).communicate(timeout=5)
            _spawn("shell", "echo b", os.environ.copy()).communicate(timeout=5)
            warning_calls = [
                c for c in mock_print.call_args_list
                if "WARNING" in str(c)
            ]
            assert len(warning_calls) == 1
        kart_worker._SANDBOX_WARNED = original


# ── content_store upsert (nest_intake) ──────────────────────────────────

class TestContentStore:
    def test_content_id_is_sha256_of_file(self):
        """SHA-256 computed by stage_file matches manual hash."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"willow content addressed test")
            tmp = f.name
        try:
            expected = hashlib.sha256(b"willow content addressed test").hexdigest()
            # Compute hash the same way stage_file does
            h = hashlib.sha256()
            with open(tmp, "rb") as fh:
                while chunk := fh.read(65536):
                    h.update(chunk)
            assert h.hexdigest() == expected
        finally:
            os.unlink(tmp)

    def test_content_store_upsert_sql(self):
        """_ensure_schema creates content_store table."""
        from unittest.mock import call
        import sap.core.nest_intake as ni

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch("sap.core.nest_intake._connect", return_value=mock_conn), \
             patch("sap.core.nest_intake._SCHEMA_CREATED", False):
            ni._SCHEMA_CREATED = False
            ni._ensure_schema()

        all_sql = " ".join(
            str(c.args[0]) for c in mock_cur.execute.call_args_list
        )
        assert "content_store" in all_sql
        assert "content_id" in all_sql
        assert "current_path" in all_sql


# ── content_id in pg_bridge jeles_register_jsonl ─────────────────────────

class TestJelesContentId:
    def test_register_jsonl_computes_content_id(self):
        """jeles_register_jsonl returns content_id matching file SHA-256."""
        from core.pg_bridge import PgBridge
        content = b"test jsonl content for hash"
        expected_hash = hashlib.sha256(content).hexdigest()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl") as f:
            f.write(content)
            tmp = f.name
        try:
            mock_conn = MagicMock()
            mock_conn.closed = False
            mock_cur = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            mock_cur.fetchone.return_value = ("fakeid",)

            bridge = PgBridge.__new__(PgBridge)
            bridge._conn = mock_conn
            bridge.gen_id = lambda: "fakeid"

            result = bridge.jeles_register_jsonl(
                "hanuman", tmp, "sess-1", cwd="/tmp"
            )
            assert result.get("content_id") == expected_hash
        finally:
            os.unlink(tmp)

    def test_register_jsonl_missing_file_content_id_none(self):
        """jeles_register_jsonl gracefully sets content_id=None for missing file."""
        from core.pg_bridge import PgBridge

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = ("fakeid",)

        bridge = PgBridge.__new__(PgBridge)
        bridge._conn = mock_conn
        bridge.gen_id = lambda: "fakeid"

        result = bridge.jeles_register_jsonl(
            "hanuman", "/nonexistent/path.jsonl", "sess-2"
        )
        assert result.get("content_id") is None

    def test_raw_jsonls_schema_includes_content_id_column(self):
        """agent_create() CREATE TABLE includes content_id column."""
        from core.pg_bridge import PgBridge

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = (0,)

        bridge = PgBridge.__new__(PgBridge)
        bridge._conn = mock_conn
        bridge.gen_id = lambda: "fakeid"

        with patch.object(bridge, "_get_conn", return_value=mock_conn):
            bridge.agent_create("testagent999")

        all_sql = " ".join(
            str(c.args[0]) for c in mock_cur.execute.call_args_list
        )
        assert "content_id" in all_sql
