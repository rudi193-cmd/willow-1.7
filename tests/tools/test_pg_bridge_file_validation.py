"""Tests for pg_bridge file path validation.
b17: PGFV1
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))

from pg_bridge import _validate_file_path


class TestValidateFilePath:
    def test_valid_home_path(self):
        home = Path.home()
        valid = str(home / "agents" / "hanuman" / "test.jsonl")
        result = _validate_file_path(valid)
        assert result.startswith(str(home.resolve()))

    def test_rejects_etc(self):
        with pytest.raises(ValueError, match="outside home"):
            _validate_file_path("/etc/passwd")

    def test_rejects_traversal(self):
        home = str(Path.home())
        traversal = home + "/agents/../../etc/passwd"
        with pytest.raises(ValueError, match="outside home"):
            _validate_file_path(traversal)

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Empty"):
            _validate_file_path("")

    def test_rejects_whitespace(self):
        with pytest.raises(ValueError, match="Empty"):
            _validate_file_path("   ")

    def test_rejects_root(self):
        with pytest.raises(ValueError, match="outside home"):
            _validate_file_path("/")
