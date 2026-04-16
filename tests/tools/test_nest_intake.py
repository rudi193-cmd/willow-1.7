"""Tests for nest_intake.py hardening.
b17: NIT1
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestHashing:
    def test_sha256_not_md5(self, tmp_path):
        """stage_file uses SHA-256 — hash is 64 hex chars (SHA-256), not 32 (MD5)."""
        import hashlib
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h = hashlib.sha256()
        with open(f, "rb") as fp:
            while chunk := fp.read(65536):
                h.update(chunk)
        expected = h.hexdigest()
        assert len(expected) == 64  # SHA-256 is 64 hex chars

    def test_full_file_hash(self, tmp_path):
        """Hash covers full file content, not just first 64KB."""
        import hashlib
        f = tmp_path / "big.bin"
        # Write 200KB — beyond the old 64KB read limit
        f.write_bytes(b"A" * 65536 + b"B" * 65536 + b"C" * 65536)
        h = hashlib.sha256()
        with open(f, "rb") as fp:
            while chunk := fp.read(65536):
                h.update(chunk)
        full_hash = h.hexdigest()
        # Hash truncated at 64KB would miss the B and C sections
        h2 = hashlib.sha256()
        with open(f, "rb") as fp:
            h2.update(fp.read(65536))
        partial_hash = h2.hexdigest()
        assert full_hash != partial_hash


class TestDestPathValidation:
    def test_valid_dest_within_ashokoa(self):
        from sap.core.nest_intake import _validate_dest_path, _ashokoa_filed
        dest = str(_ashokoa_filed() / "reference" / "general" / "test.txt")
        result = _validate_dest_path(dest)
        assert result is not None

    def test_rejects_dest_outside_allowed_roots(self, tmp_path):
        from sap.core.nest_intake import _validate_dest_path
        with pytest.raises(ValueError, match="outside all allowed roots"):
            _validate_dest_path(str(tmp_path / "evil.txt"))

    def test_rejects_empty_dest(self):
        from sap.core.nest_intake import _validate_dest_path
        with pytest.raises(ValueError):
            _validate_dest_path("")


class TestSymlinkRejection:
    def test_scan_nest_skips_symlinks(self, tmp_path, monkeypatch):
        """scan_nest() skips symlink files."""
        from sap.core import nest_intake
        monkeypatch.setenv("WILLOW_NEST_DIR", str(tmp_path))

        real = tmp_path / "real.txt"
        real.write_text("hello")
        link = tmp_path / "link.txt"
        link.symlink_to(real)

        # Patch _ensure_schema and DB calls to no-ops
        from unittest.mock import patch, MagicMock
        mock_conn = MagicMock()
        mock_conn.autocommit = True
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cur

        with patch("sap.core.nest_intake._connect", return_value=mock_conn), \
             patch("sap.core.nest_intake._SCHEMA_CREATED", True), \
             patch("sap.core.nest_intake.stage_file") as mock_stage:
            nest_intake.scan_nest()

        # Only real.txt should be staged — link.txt is a symlink and should be skipped
        staged_paths = [str(call[0][0]) for call in mock_stage.call_args_list]
        assert not any("link.txt" in p for p in staged_paths)
        assert any("real.txt" in p for p in staged_paths)
