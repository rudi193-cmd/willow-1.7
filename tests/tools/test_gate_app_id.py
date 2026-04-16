"""Tests for app_id sanitization in sap/core/gate.py.
b17: GAI1
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sap.core.gate import _validate_app_id


class TestValidateAppId:
    def test_valid_simple(self):
        assert _validate_app_id("safe-app-utety-chat") == "safe-app-utety-chat"

    def test_valid_underscore(self):
        assert _validate_app_id("hanuman") == "hanuman"

    def test_valid_alphanumeric(self):
        assert _validate_app_id("agent2") == "agent2"

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            _validate_app_id("../../../etc/passwd")

    def test_rejects_slash(self):
        with pytest.raises(ValueError):
            _validate_app_id("safe/app")

    def test_rejects_null_byte(self):
        with pytest.raises(ValueError):
            _validate_app_id("safe\x00app")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _validate_app_id("")

    def test_rejects_dotdot_embedded(self):
        with pytest.raises(ValueError):
            _validate_app_id("safe..app")

    def test_rejects_starts_with_dot(self):
        with pytest.raises(ValueError):
            _validate_app_id(".hidden")
