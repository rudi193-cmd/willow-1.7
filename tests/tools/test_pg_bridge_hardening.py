"""Tests for pg_bridge.py hardening fixes.
b17: PBH1
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))


class TestGenIdSecure:
    def test_uses_secrets(self):
        """gen_id uses secrets.randbits, not time/pid."""
        from pg_bridge import PgBridge
        with patch("secrets.randbits", return_value=12345) as mock_secrets:
            PgBridge.gen_id()
        mock_secrets.assert_called_once_with(64)

    def test_output_length(self):
        from pg_bridge import PgBridge
        result = PgBridge.gen_id(5)
        assert len(result) == 5

    def test_output_charset(self):
        from pg_bridge import PgBridge
        _ALPHABET = set("0123456789ACEHKLNRTXZ")
        for _ in range(20):
            result = PgBridge.gen_id(5)
            assert all(c in _ALPHABET for c in result)


class TestSymlinkRejection:
    def test_binder_file_rejects_symlink_source(self, tmp_path):
        from pg_bridge import PgBridge
        # Create a symlink
        real = tmp_path / "real.jsonl"
        real.write_text("{}")
        link = tmp_path / "link.jsonl"
        link.symlink_to(real)

        pg = PgBridge.__new__(PgBridge)
        # Mock DB to return the symlink path as source_path
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (str(link),)
        mock_conn = MagicMock()
        mock_conn.closed = False  # prevent _get_conn from trying to reconnect
        mock_conn.cursor.return_value = mock_cur
        pg._conn = mock_conn
        pg._psycopg2 = MagicMock()

        with patch("pg_bridge._validate_file_path", return_value=str(link)):
            result = pg.binder_file("hanuman", "jid1", str(tmp_path / "dest.jsonl"))

        assert "error" in result
        assert "symlink" in result["error"]
